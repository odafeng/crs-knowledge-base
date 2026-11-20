"""Database integration tests for the app schema (B3 #60, ADR-0016/0017).

Needs a Supabase local stack (`supabase start`). Set GUTHUB_TEST_DATABASE_URL (and GUTHUB_TEST_REST_URL plus
GUTHUB_TEST_ANON_KEY / GUTHUB_TEST_SERVICE_KEY for the Data API checks). Without them the tests skip, unless
GUTHUB_REQUIRE_DB=1, which CI sets so a missing database fails instead of passing silently.

Every test runs in a transaction that is rolled back.
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from typing import LiteralString

import psycopg
import pytest
from psycopg import errors, sql

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
REST_URL = os.environ.get("GUTHUB_TEST_REST_URL")
REQUIRED = os.environ.get("GUTHUB_REQUIRE_DB") == "1"

if not DB_URL:
    if REQUIRED:
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)

TABLES = [
    "topics",
    "papers",
    "paper_relations",
    "research_commentary",
    "news",
    "accounts",
    "comments",
    "comment_reports",
    "moderation_events",
    "comment_likes",
    "comment_like_events",
    "content_writer",
    "paper_watch_state",
    "publish_events",
    "push_subscriptions",
    "push_announcements",
    "line_broadcasts",
    "topic_subscriptions",
    "forum_posts",
    "forum_post_likes",
    "forum_reports",
    "forum_moderation_events",
    "paper_follows",
    "comment_digests",
]
VIEWS = ["public_papers", "public_news", "public_comments", "visible_forum_posts"]
CLIENT_ROLES = ["anon", "authenticated", "service_role"]


@pytest.fixture
def cur() -> Iterator[psycopg.Cursor]:
    assert DB_URL
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cursor:
        seed(cursor)
        yield cursor
        conn.rollback()


def seed(cur: psycopg.Cursor) -> None:
    # Start from empty tables whatever the database holds (e.g. after an import); the rollback restores them.
    cur.execute(
        "truncate app.topics, app.papers, app.paper_relations, app.research_commentary, app.news, app.accounts,"
        " app.comments, app.comment_reports, app.moderation_events cascade"
    )
    cur.execute(
        "insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
    )
    for pid, withdrawn in (("keynote-177", False), ("withdrawn-paper", True)):
        cur.execute(
            "insert into app.papers (id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result,"
            " bottom_line, source, reviewed_at, detail_html, withdrawn_at) values (%s, %s, 'mCRC-MSI-H', 2020,"
            " 'NEJM', 'Phase 3 RCT', '307', 'Pembrolizumab', 'PFS', 'HR 0.60', 'Use it', 'fulltext',"
            " '2026-11-01', '<p>x</p>', case when %s then now() end)",
            (pid, pid, withdrawn),
        )
    for name in ("author", "other", "admin"):
        uid = account_id(name)
        cur.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{name}@example.test"))
        cur.execute(
            "insert into app.accounts (id, display_name, is_admin) values (%s, %s, %s)",
            (uid, name.title(), name == "admin"),
        )


def account_id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"guthub-test/{name}")


def as_role(cur: psycopg.Cursor, role: str, sub: uuid.UUID | None = None) -> None:
    cur.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    claims = {"role": role, **({"sub": str(sub)} if sub else {})}
    cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))


def add_comment(cur: psycopg.Cursor, author: str = "author", *, anonymous: bool = True, status: str = "published"):
    cur.execute(
        "insert into app.comments (paper_id, author_id, body, anonymous, display_name, status)"
        " values ('keynote-177', %s, 'Useful trial', %s, %s, %s) returning id, status",
        (account_id(author), anonymous, None if anonymous else author.title(), status),
    )
    row = cur.fetchone()
    assert row
    return row


# --- closed to clients -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", CLIENT_ROLES)
@pytest.mark.parametrize("relation", TABLES + VIEWS)
def test_client_roles_cannot_read(cur: psycopg.Cursor, role: str, relation: str) -> None:
    as_role(cur, role, account_id("author"))
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute(sql.SQL("select * from app.{}").format(sql.Identifier(relation)))


@pytest.mark.parametrize("role", CLIENT_ROLES)
def test_client_roles_cannot_write_comments(cur: psycopg.Cursor, role: str) -> None:
    as_role(cur, role, account_id("author"))
    with pytest.raises(errors.InsufficientPrivilege):
        add_comment(cur)


@pytest.mark.parametrize("role", CLIENT_ROLES)
def test_client_roles_cannot_run_purge(cur: psycopg.Cursor, role: str) -> None:
    as_role(cur, role)
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute("select app.purge_deleted_authors()")


def test_rls_is_enabled_on_every_table(cur: psycopg.Cursor) -> None:
    cur.execute(
        "select relname from pg_class where relnamespace = 'app'::regnamespace and relkind = 'r' and not relrowsecurity"
    )
    assert cur.fetchall() == []


def test_no_app_table_is_published_to_realtime(cur: psycopg.Cursor) -> None:
    cur.execute("select tablename from pg_publication_tables where schemaname = 'app'")
    assert cur.fetchall() == []


@pytest.mark.skipif(not REST_URL, reason="GUTHUB_TEST_REST_URL not set")
@pytest.mark.parametrize("key_env", ["GUTHUB_TEST_ANON_KEY", "GUTHUB_TEST_SERVICE_KEY"])
@pytest.mark.parametrize("relation", ["comments", "accounts", "public_comments"])
def test_data_api_does_not_expose_app_schema(key_env: str, relation: str) -> None:
    key = os.environ[key_env]
    for headers in ({}, {"Accept-Profile": "app"}):
        request = urllib.request.Request(
            f"{REST_URL}/{relation}?select=*",
            headers={"apikey": key, "Authorization": f"Bearer {key}", **headers},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        assert caught.value.code in (404, 406), caught.value.read()


# --- guthub_api ----------------------------------------------------------------------------------------------------


def test_first_comment_waits_for_moderation_then_later_ones_publish(cur: psycopg.Cursor) -> None:
    as_role(cur, "guthub_api")
    first_id, first_status = add_comment(cur, status="published")  # requested status is ignored
    assert first_status == "pending"
    assert add_comment(cur)[1] == "pending"

    cur.execute("update app.comments set status = 'published' where id = %s", (first_id,))
    assert add_comment(cur, status="pending")[1] == "published"
    assert add_comment(cur, "other")[1] == "pending"  # the rule is per account


def test_public_comments_hide_private_and_unpublished_rows(cur: psycopg.Cursor) -> None:
    as_role(cur, "guthub_api")
    visible, _ = add_comment(cur)
    cur.execute("update app.comments set status = 'published' where id = %s", (visible,))
    add_comment(cur, "other")  # pending: first comment of that account
    deleted, _ = add_comment(cur)
    cur.execute("update app.comments set deleted_at = now() where id = %s", (deleted,))
    hidden, _ = add_comment(cur, anonymous=False)
    cur.execute("update app.comments set status = 'hidden' where id = %s", (hidden,))

    cur.execute("select * from app.public_comments")
    assert cur.description
    columns = {column.name for column in cur.description}
    assert columns == {"id", "paper_id", "body", "anonymous", "display_name", "created_at", "updated_at"}
    assert [row[0] for row in cur.fetchall()] == [visible]


def test_withdrawn_content_is_not_public(cur: psycopg.Cursor) -> None:
    as_role(cur, "guthub_api")
    cur.execute("select id from app.public_papers")
    assert cur.fetchall() == [("keynote-177",)]
    cur.execute("select column_name from information_schema.columns where table_name = 'public_papers'")
    assert ("withdrawn_at",) not in cur.fetchall()


@pytest.mark.parametrize(
    "statement",
    [
        "update app.moderation_events set reason = 'edited'",
        "delete from app.moderation_events",
        "delete from app.comments",
        "delete from app.accounts",
        "update app.papers set result = 'tampered'",
        "update app.comment_reports set reason = 'edited'",
    ],
)
def test_guthub_api_cannot_rewrite_history_or_content(cur: psycopg.Cursor, statement: LiteralString) -> None:
    as_role(cur, "guthub_api")
    with pytest.raises(errors.InsufficientPrivilege):
        cur.execute(statement)


def test_guthub_api_can_append_audit_and_reports(cur: psycopg.Cursor) -> None:
    as_role(cur, "guthub_api")
    comment_id, _ = add_comment(cur)
    cur.execute(
        "insert into app.moderation_events (comment_id, actor_id, action, reason)"
        " values (%s, %s, 'reveal_author', 'abuse report')",
        (comment_id, account_id("admin")),
    )
    cur.execute(
        "insert into app.comment_reports (comment_id, reporter_id, reason) values (%s, %s, 'spam') returning id",
        (comment_id, account_id("other")),
    )
    cur.execute("update app.comment_reports set resolved_at = now()")
    assert cur.rowcount == 1


# --- constraints ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "error"),
    [
        (  # comment on a paper that does not exist
            "insert into app.comments (paper_id, author_id, body, anonymous) values ('nope', %(author)s, 'x', true)",
            errors.ForeignKeyViolation,
        ),
        (  # anonymous comment must not carry a public name
            "insert into app.comments (paper_id, author_id, body, anonymous, display_name)"
            " values ('keynote-177', %(author)s, 'x', true, 'Author')",
            errors.CheckViolation,
        ),
        (  # signed comment needs a public name
            "insert into app.comments (paper_id, author_id, body, anonymous) values ('keynote-177', %(author)s, 'x', false)",
            errors.CheckViolation,
        ),
        (  # blank body
            "insert into app.comments (paper_id, author_id, body, anonymous) values ('keynote-177', %(author)s, '   ', true)",
            errors.CheckViolation,
        ),
        (  # an undeleted comment must keep its author mapping
            "insert into app.comments (paper_id, author_id, body, anonymous) values ('keynote-177', null, 'x', true)",
            errors.CheckViolation,
        ),
        (
            "insert into app.paper_relations (paper_id, target_id, type) values ('keynote-177', 'missing', 'builds_on')",
            errors.ForeignKeyViolation,
        ),
        (
            "insert into app.paper_relations (paper_id, target_id, type) values ('keynote-177', 'keynote-177', 'builds_on')",
            errors.CheckViolation,
        ),
        (
            "insert into app.research_commentary (paper_id, title, journal, type, summary, critique, new_data, added_at)"
            " values ('keynote-177', 'Letter', 'NEJM', 'Letter', 's', false, false, '2026-01-01')",
            errors.CheckViolation,
        ),
        (
            "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result,"
            " bottom_line, source, reviewed_at, detail_html) select 'dup', slug, topic_key, year, journal, study_type,"
            " regimen, endpoint, result, bottom_line, source, reviewed_at, detail_html from app.papers"
            " where id = 'keynote-177'",
            errors.UniqueViolation,
        ),
        (
            "update app.papers set n = '[1]' where id = 'keynote-177'",
            errors.CheckViolation,
        ),
    ],
)
def test_constraints(cur: psycopg.Cursor, statement: LiteralString, error: type[Exception]) -> None:
    with pytest.raises(error):
        cur.execute(statement, {"author": account_id("author")})


def test_one_report_per_reporter_and_comment(cur: psycopg.Cursor) -> None:
    comment_id, _ = add_comment(cur)
    report = "insert into app.comment_reports (comment_id, reporter_id, reason) values (%s, %s, 'spam')"
    cur.execute(report, (comment_id, account_id("other")))
    with pytest.raises(errors.UniqueViolation):
        cur.execute(report, (comment_id, account_id("other")))


# --- retention -----------------------------------------------------------------------------------------------------


def test_purge_clears_author_mapping_only_after_90_days(cur: psycopg.Cursor) -> None:
    old, _ = add_comment(cur)
    recent, _ = add_comment(cur)
    cur.execute("update app.comments set deleted_at = now() - interval '91 days' where id = %s", (old,))
    cur.execute("update app.comments set deleted_at = now() - interval '30 days' where id = %s", (recent,))

    as_role(cur, "guthub_api")
    cur.execute("select app.purge_deleted_authors()")
    cur.execute("select id, author_id is null from app.comments where id in (%s, %s)", (old, recent))
    assert dict(cur.fetchall()) == {old: True, recent: False}


def test_purge_removes_accounts_deleted_over_90_days_ago(cur: psycopg.Cursor) -> None:
    cur.execute("update app.accounts set deleted_at = now() - interval '91 days' where id = %s", (account_id("other"),))
    cur.execute(
        "update app.accounts set deleted_at = now() - interval '10 days' where id = %s", (account_id("author"),)
    )

    as_role(cur, "guthub_api")
    cur.execute("select app.purge_deleted_authors()")
    cur.execute("select id from app.accounts order by display_name")
    assert {row[0] for row in cur.fetchall()} == {account_id("admin"), account_id("author")}


def test_purging_an_account_soft_deletes_its_remaining_comments(cur: psycopg.Cursor) -> None:
    live, _ = add_comment(cur, "other")
    cur.execute("update app.accounts set deleted_at = now() - interval '91 days' where id = %s", (account_id("other"),))

    as_role(cur, "guthub_api")
    cur.execute("select app.purge_deleted_authors()")
    cur.execute("select author_id, deleted_at is not null from app.comments where id = %s", (live,))
    assert cur.fetchone() == (None, True)


def test_deleting_an_auth_user_directly_still_succeeds(cur: psycopg.Cursor) -> None:
    live, _ = add_comment(cur)
    cur.execute("delete from auth.users where id = %s", (account_id("author"),))
    cur.execute("select author_id, deleted_at is not null from app.comments where id = %s", (live,))
    assert cur.fetchone() == (None, True)


def add_forum_post(cur: psycopg.Cursor, author: str = "author", thread: uuid.UUID | None = None) -> uuid.UUID:
    cur.execute(
        "insert into app.forum_posts (thread_id, title, author_id, body, anonymous) values (%s, %s, %s, 'b', true)"
        " returning id",
        (thread, None if thread else "t", account_id(author)),
    )
    row = cur.fetchone()
    assert row
    return row[0]


def test_forum_posts_follow_the_comment_retention_rules(cur: psycopg.Cursor) -> None:
    old = add_forum_post(cur)
    recent = add_forum_post(cur, thread=old)
    live = add_forum_post(cur, "other")
    cur.execute("update app.forum_posts set deleted_at = now() - interval '91 days' where id = %s", (old,))
    cur.execute("update app.forum_posts set deleted_at = now() - interval '30 days' where id = %s", (recent,))
    cur.execute("update app.accounts set deleted_at = now() - interval '91 days' where id = %s", (account_id("other"),))

    as_role(cur, "guthub_api")
    cur.execute("select app.purge_deleted_authors()")
    cur.execute("select id, author_id is null, deleted_at is not null from app.forum_posts")
    assert {row[0]: row[1:] for row in cur.fetchall()} == {old: (True, True), recent: (False, True), live: (True, True)}


def test_first_forum_post_waits_and_visible_posts_hide_the_author(cur: psycopg.Cursor) -> None:
    first = add_forum_post(cur)
    cur.execute("select status from app.forum_posts where id = %s", (first,))
    assert cur.fetchone() == ("pending",)
    cur.execute("update app.forum_posts set status = 'published' where id = %s", (first,))
    reply = add_forum_post(cur, thread=first)
    cur.execute("select status from app.forum_posts where id = %s", (reply,))
    assert cur.fetchone() == ("published",)

    as_role(cur, "guthub_api")
    cur.execute("select * from app.visible_forum_posts")
    columns = {c.name for c in cur.description or ()}
    assert "author_id" not in columns and "pinned_at" in columns and len(cur.fetchall()) == 2
