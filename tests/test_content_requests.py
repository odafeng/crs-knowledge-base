"""Accept and unpublish requests after cutover (worker/content_requests.py, E3 #76).

The selection tests need nothing; the publishing tests need Supabase local (GUTHUB_TEST_DATABASE_URL) like
test_content_writer.py, and run inside a transaction that is rolled back.
"""

import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import content_writer
import pytest
from import_content import apply, build_rows

from create_issues import format_issue_body
from test_publish import TODAY, _paper

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
import content_requests  # noqa: E402

REPO = "owner/repo"
DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
CONTENT = "app.topics, app.papers, app.paper_relations, app.research_commentary, app.news"


def issue(number: int, login: str, labels: list[str], title: str = "t", body: str = "") -> dict:
    return {"number": number, "user": {"login": login}, "labels": [{"name": n} for n in labels], "title": title,
            "body": body}  # fmt: skip


class FakeGh:
    def __init__(self, issues: list[dict]) -> None:
        self.issues, self.calls = issues, []

    def __call__(self, *args: str) -> str:
        if args[0] == "api":
            return json.dumps([self.issues])
        self.calls.append(args)
        return ""

    def said(self, number: int) -> str:
        return "\n".join(c[c.index("--body") + 1] for c in self.calls if c[:3] == ("issue", "comment", str(number)))

    def did(self, *args: str) -> bool:
        return any(c[: len(args)] == args for c in self.calls)


# --- which issues count as requests ---------------------------------------------------------------------------------


def test_only_requests_the_pipeline_opened_are_taken():
    bot, owner = content_requests.ACTIONS_BOT, "owner"
    issues = [
        issue(5, owner, ["accepted"]),  # Paper Watch on Cloud Run opens issues with the owner's token
        issue(3, bot, ["accepted", "kb-update"]),
        issue(4, "someone", ["accepted"]),  # a reader's issue is never published, whatever its labels
        issue(6, bot, ["unpublish-request"], "[撤下] x"),
        issue(7, owner, ["unpublish-request"], "[撤下] y"),  # only the Unpublish workflow opens these
        issue(8, bot, ["unpublish-request"], "something else"),
        issue(9, bot, ["held"]),
    ]
    accepts, unpublishes = content_requests.pending(issues, owner)
    assert [i["number"] for i in accepts] == [3, 5]
    assert [i["number"] for i in unpublishes] == [6]


def test_pull_requests_are_not_issues():
    gh = FakeGh([issue(1, "owner", ["accepted"]), {**issue(2, "owner", ["accepted"]), "pull_request": {}}])
    assert [i["number"] for i in content_requests.open_issues(gh, REPO)] == [1]


# --- publishing through the database --------------------------------------------------------------------------------


@pytest.fixture
def db_writer(tmp_path) -> Iterator:
    if not DB_URL:
        if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
            pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
        pytest.skip("no test database")
    import shutil

    import psycopg

    for name in ("data", "docs"):
        shutil.copytree(ROOT / name, tmp_path / name)
    with psycopg.connect(DB_URL) as conn, conn.transaction(force_rollback=True):
        conn.execute(f"truncate {CONTENT}, app.comments, app.comment_reports, app.moderation_events cascade")
        conn.execute("truncate app.publish_events, app.paper_watch_state")
        conn.execute("update app.content_writer set writer = 'json', watermark = null")
        apply(conn, build_rows(ROOT))
        content_writer.cutover(conn, tmp_path)
        yield conn


def public(conn, paper_id: str) -> bool:
    return conn.execute("select count(*) from app.public_papers where id = %s", (paper_id,)).fetchone()[0] == 1


def test_an_accepted_issue_is_published_reported_and_closed(db_writer):
    gh = FakeGh([issue(12, content_requests.ACTIONS_BOT, ["accepted"], body=format_issue_body(_paper()))])
    assert content_requests.run(gh, REPO, TODAY, db_writer) == 0
    assert public(db_writer, "test-auto-2026")
    status = db_writer.execute("select review_status from app.papers where id = 'test-auto-2026'").fetchone()[0]
    assert status == "accepted"
    assert gh.said(12).startswith("已發布：publish test-auto-2026")
    assert gh.did("issue", "close", "12")


def test_a_run_after_a_crash_closes_the_issue_without_publishing_again(db_writer):
    body = format_issue_body(_paper())
    content_requests.run(FakeGh([issue(12, "owner", ["accepted"], body=body)]), "owner/repo", TODAY, db_writer)
    # The job died before closing #12; the next run finds it still open.
    gh = FakeGh([issue(12, "owner", ["accepted"], body=body)])
    assert content_requests.run(gh, "owner/repo", TODAY, db_writer) == 0
    assert db_writer.execute("select count(*) from app.publish_events").fetchone()[0] == 1
    assert gh.said(12).startswith("已發布：publish test-auto-2026") and gh.did("issue", "close", "12")


def test_a_request_that_cannot_be_published_is_explained_and_loses_its_label(db_writer):
    gh = FakeGh([issue(13, content_requests.ACTIONS_BOT, ["accepted"], body="no payload here")])
    assert content_requests.run(gh, REPO, TODAY, db_writer) == 1
    assert "沒有可發布的資料" in gh.said(13)
    assert gh.did("issue", "edit", "13", "--repo", REPO, "--remove-label", "accepted")
    assert not gh.did("issue", "close", "13")
    assert db_writer.execute("select count(*) from app.publish_events").fetchone()[0] == 0


def test_an_unpublish_request_withdraws_the_paper(db_writer):
    content_requests.run(
        FakeGh([issue(12, "owner", ["accepted"], body=format_issue_body(_paper()))]), "owner/repo", TODAY, db_writer
    )
    gh = FakeGh([issue(14, content_requests.ACTIONS_BOT, ["unpublish-request"], "[撤下] test-auto-2026")])
    assert content_requests.run(gh, REPO, TODAY, db_writer) == 0
    assert not public(db_writer, "test-auto-2026")
    assert gh.said(14).startswith("已撤下：") and gh.did(
        "issue", "close", "14", "--repo", REPO, "--reason", "completed"
    )


def test_an_unpublish_request_for_a_hand_curated_paper_is_refused(db_writer):
    curated = db_writer.execute("select id from app.papers where review_status is null limit 1").fetchone()[0]
    gh = FakeGh([issue(15, content_requests.ACTIONS_BOT, ["unpublish-request"], f"[撤下] {curated}")])
    assert content_requests.run(gh, REPO, TODAY, db_writer) == 1
    assert public(db_writer, curated)
    assert "人工整理" in gh.said(15) and gh.did("issue", "close", "15", "--repo", REPO, "--reason", "not planned")
