"""Accept and unpublish requests after cutover, as the Cloud Run job content-requests (E3 #76, ADR-0021).

Before cutover the paper-accept and unpublish workflows edit the JSON and commit it. Once data/WRITER says postgres
the database is the only writer and its credentials stay in Secret Manager, so those workflows only start this job.
GitHub may start the job but not change what it runs (it has run.jobs.run, not runWithOverrides), so the job takes
no arguments and reads the requests from the open issues themselves:

- labelled `accepted` and opened by the pipeline (github-actions before cutover, the repository owner's token that
  Paper Watch uses after it): publish, comment, close. A request that cannot be published gets the reasons as a
  comment and loses the label, so adding the label again retries it. Digests of 3/5 papers are left to Paper Watch,
  which alone can classify their picks (#218).
- labelled `unpublish-request`, opened by github-actions (the Unpublish workflow), titled `[撤下] <target>`:
  unpublish, comment, close.
- rows in app.content_requests that the API recorded for an admin's button on the site (E6 #159): mark an
  auto-published paper or story reviewed, or take it down; the outcome goes back into the row.

Each request is recorded in app.publish_events under a key named after its issue, so a job that dies after the
database write but before closing the issue only reports and closes it on the next run. The issues are listed through
the REST API rather than search, which can lag behind a label that was added a moment ago. Exits 1 if any request
failed, so the job-failure alert reports it.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from accept_issue import accept  # noqa: E402
from content_store import DATABASE_ENV, content_session  # noqa: E402
from digest import is_digest  # noqa: E402
from issue_data import extract  # noqa: E402
from publish import PublishError, mark_reviewed, unpublish, unpublish_story  # noqa: E402
from revalidate_site import revalidate_site  # noqa: E402

ACCEPTED = "accepted"
UNPUBLISH = "unpublish-request"
UNPUBLISH_TITLE = "[撤下] "
ACTIONS_BOT = "github-actions[bot]"
TAIPEI = ZoneInfo("Asia/Taipei")

type Gh = Callable[..., str]
type Issue = dict[str, Any]


def gh_cli(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issues(gh: Gh, repo: str) -> list[Issue]:
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues?state=open&per_page=100"))
    return [issue for page in pages for issue in page if "pull_request" not in issue]


def _labelled(issue: Issue, label: str) -> bool:
    return any(item["name"] == label for item in issue["labels"])


def pending(issues: list[Issue], owner: str) -> tuple[list[Issue], list[Issue]]:
    """(accept requests, unpublish requests), oldest first; anything not opened by the pipeline is ignored."""
    issues = sorted(issues, key=lambda issue: issue["number"])
    accepts = [
        i
        for i in issues
        # A digest's picks need classifying, which only Paper Watch can do (#218)
        if _labelled(i, ACCEPTED) and i["user"]["login"] in (ACTIONS_BOT, owner) and not is_digest(i.get("body"))
    ]
    unpublishes = [
        i
        for i in issues
        if _labelled(i, UNPUBLISH) and i["user"]["login"] == ACTIONS_BOT and i["title"].startswith(UNPUBLISH_TITLE)
    ]
    return accepts, unpublishes


def accept_request(issue: Issue, today: str, gh: Gh, repo: str, conn: Any = None) -> bool:
    number, body = str(issue["number"]), issue["body"] or ""
    action = "publish_paper" if extract(body, "paper") else "publish_commentary"
    try:
        with content_session(action, f"issue-{number}", key=f"{action}:issue-{number}", conn=conn) as session:
            summary = session.done or session.record(accept(body, today, session.kb))
    except PublishError as error:
        reasons = "\n".join(f"- {reason}" for reason in error.reasons)
        gh("issue", "comment", number, "--repo", repo, "--body",
           f"無法發布：\n{reasons}\n\n修正後重新加上 `accepted` label 即可重試。")  # fmt: skip
        gh("issue", "edit", number, "--repo", repo, "--remove-label", ACCEPTED)
        return False
    gh("issue", "comment", number, "--repo", repo, "--body",
       f"已發布：{summary}。網站最多 5 分鐘後更新；要撤下請到 Actions 執行 Unpublish。")  # fmt: skip
    gh("issue", "close", number, "--repo", repo, "--reason", "completed")
    return True


def unpublish_request(issue: Issue, gh: Gh, repo: str, conn: Any = None) -> bool:
    number, target = str(issue["number"]), issue["title"].removeprefix(UNPUBLISH_TITLE).strip()
    try:
        with content_session("unpublish", target, key=f"unpublish:issue-{number}", conn=conn) as session:
            removed = session.done or session.record(unpublish(target, session.kb))
    except PublishError as error:
        reasons = "\n".join(f"- {reason}" for reason in error.reasons)
        gh("issue", "comment", number, "--repo", repo, "--body", f"無法撤下：\n{reasons}")
        gh("issue", "close", number, "--repo", repo, "--reason", "not planned")
        return False
    gh("issue", "comment", number, "--repo", repo, "--body", f"已撤下：{removed}。網站最多 5 分鐘後更新。")
    gh("issue", "close", number, "--repo", repo, "--reason", "completed")
    return True


def site_request(row: dict[str, Any], conn: Any = None) -> tuple[bool, str]:
    """An admin's button on the site (E6 #159), recorded by the API in app.content_requests."""
    action, kind, target = row["action"], row["kind"], row["target"]
    try:
        with content_session(action, target, key=f"{action}:request-{row['id']}", conn=conn) as session:
            if session.done:
                return True, session.done
            if action == "review":
                return True, session.record(mark_reviewed(kind, target, session.kb))
            remove = unpublish_story if kind == "news" else unpublish
            return True, session.record(remove(target, session.kb))
    except PublishError as error:
        return False, "；".join(error.reasons)


def site_requests(store: Any, conn: Any = None) -> list[bool]:
    rows = store.execute(
        "select id, action, kind, target from app.content_requests where done_at is null order by id"
    ).fetchall()
    results = []
    for row in rows:
        ok, result = site_request(dict(zip(("id", "action", "kind", "target"), row, strict=True)), conn)
        store.execute(
            "update app.content_requests set done_at = now(), ok = %s, result = %s where id = %s", (ok, result, row[0])
        )
        results.append(ok)
    return results


def run(gh: Gh, repo: str, today: str, conn: Any = None, store: Any = None) -> int:
    """`store` lists and closes the site's requests; `conn`, when given, is also the content writer's connection."""
    accepts, unpublishes = pending(open_issues(gh, repo), repo.split("/")[0])
    results = [accept_request(issue, today, gh, repo, conn) for issue in accepts]
    results += [unpublish_request(issue, gh, repo, conn) for issue in unpublishes]
    site = site_requests(store, conn) if store is not None else []
    if any(results + site):
        revalidate_site()
    print(json.dumps({"job": "content-requests", "accept": len(accepts), "unpublish": len(unpublishes),
                      "site": len(site), "failed": (results + site).count(False)}))  # fmt: skip
    return 0 if all(results + site) else 1


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo or not os.environ.get(DATABASE_ENV):
        print(f"GITHUB_REPOSITORY and {DATABASE_ENV} are required", file=sys.stderr)
        return 2
    import psycopg

    with psycopg.connect(os.environ[DATABASE_ENV], autocommit=True) as store:
        return run(gh_cli, repo, datetime.now(TAIPEI).date().isoformat(), store=store)


if __name__ == "__main__":
    sys.exit(main())
