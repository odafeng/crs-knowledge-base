"""Papers that scored one under the threshold, listed for the maintainer to pick from (#218).

A 3/5 paper gets no KB entry and is tracked, so the scan never sees it again. Lowering the threshold would open
review issues with nothing to publish and loosen auto-publishing. Instead each run lists its 3/5 papers in one
digest issue; the maintainer ticks the ones worth a page and adds `accepted`, and the next Paper Watch run sends
the ticked papers through the --review path (#214), which writes the entry whatever the score.

The content-requests job skips digests: it has no Anthropic key, so only Paper Watch can classify the picks.
"""

import json
import sys
from collections import defaultdict

from config import GITHUB_REPO
from gh_cli import ensure_labels, run_gh
from issue_data import checkbox, checked_indices, embed, extract

LABEL = "paper-digest"
ACCEPTED = "accepted"
KIND = "digest"
BOT_LOGINS = {"app/github-actions", "github-actions[bot]"}


def format_digest_body(papers: list[dict], today: str) -> str:
    lines = [
        f"以下論文在 {today} 的 Paper Watch 評為 3 分（門檻 4 分），沒有發布，之後的掃描也不會再處理。",
        "",
        "**送審方式**：勾選想收錄的論文，再加上 `accepted` label。下一次 Paper Watch 執行時（排程每天 16:00）"
        "會重新分類勾選的論文，每篇開一張審核 issue，每篇會再花一次分類費。沒勾的論文不會再處理。",
    ]
    by_topic: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, p in enumerate(papers):
        by_topic[p.get("topic", "")].append((i, p))
    for topic, items in by_topic.items():
        lines += ["", f"### `{topic}`"]
        for i, p in items:
            link = f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
            source = " ".join(str(s) for s in (p.get("journal"), p.get("year")) if s)
            lines.append(f"{checkbox(i)} [{p.get('title', '').strip()}]({link})（{source}，PMID {p['pmid']}）")
            if p.get("ai_analysis"):
                lines.append(f"  - AI：{p['ai_analysis'].strip()}")
    payload = [{"index": i, "pmid": p["pmid"], "topic": p.get("topic", "")} for i, p in enumerate(papers)]
    lines += ["", embed(KIND, payload)]
    return "\n".join(lines)


def create_digest_issue(papers: list[dict], today: str, dry_run: bool = False) -> None:
    """One digest issue per run for the papers that scored one under the threshold."""
    papers = [p for p in papers if p.get("pmid")]  # --review fetches by PMID
    if not papers:
        return
    title = f"[待挑選] {len(papers)} 篇 3 分論文（{today}）"
    body = format_digest_body(papers, today)
    if dry_run:
        print(f"\n{'=' * 60}\nISSUE: {title}\n{'=' * 60}\n{body[:500]}\n...")
        return
    ensure_labels({LABEL})
    ok, url = run_gh(["issue", "create", "--title", title, "--label", LABEL, "--body", body])
    if ok:
        print(f"  Created digest issue: {url}")
    else:
        print("  [ERROR] Failed to create digest issue", file=sys.stderr)


def picked(body: str) -> dict[str, list[str]]:
    """PMIDs the maintainer ticked, by topic."""
    ticked = checked_indices(body)
    picks: dict[str, list[str]] = defaultdict(list)
    for item in extract(body, KIND) or []:
        if item["index"] in ticked:
            picks[item["topic"]].append(item["pmid"])
    return dict(picks)


def is_digest(body: str | None) -> bool:
    return extract(body or "", KIND) is not None


def accepted_digests() -> list[dict] | None:
    """Open digests labelled `accepted` that the pipeline opened, oldest first; None if gh failed."""
    ok, out = run_gh(
        ["issue", "list", "--state", "open", "--label", LABEL, "--label", ACCEPTED,
         "--json", "number,body,author", "--limit", "50"]
    )  # fmt: skip
    if not ok:
        return None
    owner = GITHUB_REPO.split("/")[0]
    issues = [i for i in json.loads(out or "[]") if i["author"]["login"] in BOT_LOGINS | {owner}]
    return sorted(issues, key=lambda i: i["number"])


def finish(number: int, sent: int, opened: int) -> None:
    """Report the outcome on the digest and close it; with nothing ticked, ask again and drop the label."""
    n = str(number)
    if not sent:
        run_gh(
            ["issue", "comment", n, "--body", "沒有勾選任何論文。勾選想收錄的論文後，重新加上 `accepted` label 即可。"]
        )
        run_gh(["issue", "edit", n, "--remove-label", ACCEPTED])
        return
    report = f"已重新分類勾選的 {sent} 篇，開出 {opened} 張審核 issue（label `new-paper`）。"
    if opened < sent:
        report += f"其中 {sent - opened} 篇的 issue 沒開成，請看 paper-watch job 的 log。"
    run_gh(["issue", "comment", n, "--body", report])
    run_gh(["issue", "close", n, "--reason", "completed"])
