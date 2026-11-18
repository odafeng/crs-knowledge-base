"""GutHub AI's first forum threads (H9 #161): only approved drafts are posted, once, signed and marked AI."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import forum_ai_topics as fa
from test_import_content import DB_URL, needs_db

DRAFT = {"key": "k", "approved": True, "title": "側方淋巴結怎麼處理？", "topicKey": None, "paperId": None,
         "body": "想聽聽大家的做法。\n\n來源：站上整理的條目。"}  # fmt: skip


def test_the_shipped_drafts_name_their_sources_and_wait_for_review() -> None:
    drafts = fa.load()
    assert 5 <= len(drafts) <= 8
    assert len({d["key"] for d in drafts}) == len(drafts)
    for draft in drafts:
        assert fa.problems(draft) == []
        assert draft["paperId"] and draft["topicKey"]
    assert all(isinstance(d["approved"], bool) for d in drafts)  # the maintainer flips each after reading it


def test_drafts_without_sources_or_too_long_are_refused() -> None:
    assert fa.problems({**DRAFT, "body": "沒有出處"}) == ["k: body must name its sources on the site"]
    assert fa.problems({**DRAFT, "title": "長" * 121}) == ["k: title must be 1-120 characters"]


@pytest.fixture
def conn():
    if not DB_URL:
        pytest.skip("no test database")
    import psycopg

    with psycopg.connect(DB_URL) as connection, connection.transaction(force_rollback=True):
        connection.execute("delete from app.forum_posts where ai")
        yield connection


@needs_db
def test_approved_drafts_are_posted_once_as_published_ai_threads(conn) -> None:
    waiting = {**DRAFT, "key": "w", "approved": False, "title": "還沒確認"}
    report = fa.post(conn, [DRAFT, waiting])
    assert (report["posted"], report["pending"]) == (["k"], ["w"])
    row = conn.execute(
        "select status::text, ai, author_id, anonymous, display_name, body from app.forum_posts where title = %s",
        (DRAFT["title"],),
    ).fetchone()
    assert row[:5] == ("published", True, None, False, "GutHub AI")
    assert row[5].endswith(fa.FOOTER)
    assert fa.post(conn, [DRAFT])["skipped"] == ["k"]  # running again posts nothing twice
    assert conn.execute("select count(*) from app.forum_posts where ai").fetchone()[0] == 1


@needs_db
def test_a_bad_link_stops_the_whole_run(conn) -> None:
    with pytest.raises(ValueError, match="not public"):
        fa.post(conn, [DRAFT, {**DRAFT, "key": "x", "title": "另一題", "paperId": "no-such-paper"}])
    assert conn.execute("select count(*) from app.forum_posts where ai").fetchone()[0] == 0


@needs_db
def test_the_api_role_cannot_post_as_ai(conn) -> None:
    import psycopg

    conn.execute("set local role guthub_api")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "insert into app.forum_posts (title, body, anonymous, display_name, ai) values ('t', 'b', false, 'x', true)"
        )
