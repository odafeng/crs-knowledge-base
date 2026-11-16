"""Scheduled maintenance against the real database (E3 #76): the purge the privacy policy promises (ADR-0017)."""

import os
import uuid
from collections.abc import Iterator
from urllib.parse import quote

import psycopg
import pytest

from guthub_api import maintenance

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"


def sql(statement, params=None):
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def comments() -> Iterator[dict[str, uuid.UUID]]:
    paper = f"e3-{uuid.uuid4().hex[:8]}"
    author = uuid.uuid4()
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    sql(
        "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result, bottom_line,"
        " source, reviewed_at, detail_html) values (%s, %s, 'mCRC-MSI-H', 2024, 'NEJM', 'Phase 3 RCT', 'Drug', 'OS',"
        " 'HR 0.5', 'Use it', 'fulltext', '2026-11-01', '<p>x</p>')",
        (paper, paper),
    )
    sql("insert into auth.users (id, email) values (%s, %s)", (author, f"{author}@example.test"))
    sql("insert into app.accounts (id, display_name) values (%s, 'Author')", (author,))
    ids = {}
    for name, deleted_days in (("old", 91), ("recent", 10), ("live", None)):
        ids[name] = sql(
            "insert into app.comments (paper_id, author_id, body, anonymous, deleted_at) values"
            " (%s, %s, %s, true, case when %s::int is null then null else now() - %s::int * interval '1 day' end)"
            " returning id",
            (paper, author, name, deleted_days, deleted_days),
        )[0][0]
    yield ids
    sql("delete from app.comments where paper_id = %s", (paper,))
    sql("delete from app.papers where id = %s", (paper,))
    sql("delete from auth.users where id = %s", (author,))


def test_purge_clears_only_mappings_deleted_over_90_days_ago(comments, monkeypatch, capsys) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", API_DB_URL)
    assert maintenance.main(["purge-deleted-authors"]) == 0
    authors = dict(
        sql("select body, author_id is not null from app.comments where id = any(%s)", (list(comments.values()),))
    )
    assert authors == {"old": False, "recent": True, "live": True}
    assert '"clearedCommentAuthors": 1' in capsys.readouterr().out


def test_purge_needs_a_database(monkeypatch) -> None:
    monkeypatch.delenv("GUTHUB_DATABASE_URL", raising=False)
    assert maintenance.main(["purge-deleted-authors"]) == 1
