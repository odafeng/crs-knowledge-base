"""Following papers and the daily comment digest (G8 #119) against the real database and a mock Resend. Needs
GUTHUB_TEST_DATABASE_URL; skips without it unless GUTHUB_REQUIRE_DB=1. No test sends a real email."""

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import jwt
import psycopg
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from psycopg import sql as pg_sql

from guthub_api import maintenance
from guthub_api.auth import TokenVerifier
from guthub_api.daily import TAIPEI
from guthub_api.digest import send_digests
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"
SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "contracts/openapi.yaml").read_text())
ISSUER = "http://auth.test/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())
ORIGIN = "https://guthub.tw"
RESEND_KEY = "re_test_key"


def sql(statement: Any, params: Any = None) -> list[Any]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else []


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


@dataclass
class World:
    day: date
    paper: str
    quiet: str  # followed, but nobody comments on it that day
    withdrawn: str
    reader: uuid.UUID
    writer: uuid.UUID
    newbie: uuid.UUID  # signed in, no display name yet

    def headers(self, user: uuid.UUID) -> dict[str, str]:
        now = int(time.time())
        claims = {"sub": str(user), "aud": "authenticated", "iss": ISSUER, "role": "authenticated", "iat": now}
        return {"Authorization": f"Bearer {jwt.encode({**claims, 'exp': now + 600}, KEY, algorithm='ES256')}"}

    def at(self, hour: int) -> datetime:
        return datetime(self.day.year, self.day.month, self.day.day, hour, tzinfo=TAIPEI)

    def comment(self, author: uuid.UUID, paper: str, at: datetime, *, status: str = "published") -> str:
        """A comment as it would stand after moderation; published_at is set to `at` like the trigger would."""
        [(cid,)] = sql(
            "insert into app.comments (paper_id, author_id, body, anonymous, display_name) values (%s, %s, %s,"
            " false, 'Writer Name') returning id",
            (paper, author, f"comment {uuid.uuid4().hex[:6]}"),
        )
        # Status first (the trigger stamps published_at with now()), then back-date both times.
        sql("update app.comments set status = %s where id = %s", (status, cid))
        sql(
            "update app.comments set created_at = %s, published_at = case when status = 'published' then %s end"
            " where id = %s",
            (at, at, cid),
        )
        return str(cid)


@pytest.fixture
def world() -> Iterator[World]:
    run = uuid.uuid4().hex[:8]
    # A day far from real content, so the digest function only sees this test's comments.
    w = World(
        date(2032, 5, 1 + int(run, 16) % 28), f"g8-{run}", f"g8-{run}-quiet", f"g8-{run}-gone",
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(),
    )  # fmt: skip
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    for pid, regimen, withdrawn in ((w.paper, "Nivo + ipi", False), (w.quiet, "Quiet", False),
                                    (w.withdrawn, "Gone", True)):  # fmt: skip
        sql(
            "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result,"
            " bottom_line, source, reviewed_at, detail_html, withdrawn_at) values (%s, %s, 'mCRC-MSI-H', 2026,"
            " 'Lancet', 'Phase 3 RCT', %s, 'OS', 'HR 0.5', 'Use it', 'fulltext', '2026-11-01', '<p>x</p>',"
            " case when %s then now() end)",
            (pid, pid, regimen, withdrawn),
        )
    for uid, name in ((w.reader, "Reader"), (w.writer, "Writer Name"), (w.newbie, None)):
        sql("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@example.test"))
        if name:
            sql("insert into app.accounts (id, display_name) values (%s, %s)", (uid, name))
    yield w
    papers = [w.paper, w.quiet, w.withdrawn]
    sql("delete from app.comments where paper_id = any(%s)", (papers,))
    sql("delete from auth.users where id = any(%s)", ([w.reader, w.writer, w.newbie],))
    sql("delete from app.papers where id = any(%s)", (papers,))


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


class MockResend:
    """Answers like Resend's POST /emails, with scripted statuses; remembers idempotency keys it accepted."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.statuses: list[int] = []

    def handler(self) -> type[BaseHTTPRequestHandler]:
        resend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                resend.requests.append(
                    {
                        "path": self.path,
                        "auth": self.headers.get("Authorization"),
                        "key": self.headers.get("Idempotency-Key"),
                        "body": body,
                    }
                )
                status = resend.statuses.pop(0) if resend.statuses else 200
                self.send_response(status)
                self.send_header("content-length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        return Handler


@pytest.fixture
def resend() -> Iterator[tuple[str, MockResend]]:
    mock = MockResend()
    server = ThreadingHTTPServer(("127.0.0.1", 0), mock.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", mock
    server.shutdown()


# --- following ---------------------------------------------------------------------------------------------------


def test_follow_unfollow_and_the_digest_switch(client: TestClient, world: World) -> None:
    h = world.headers(world.reader)
    start = client.get(f"{API_PREFIX}/me/follows", headers=h)
    assert start.status_code == 200 and start.headers["Cache-Control"] == "private, no-store"
    assert start.json() == {"papers": [], "commentDigest": True}
    followed = client.put(f"{API_PREFIX}/me/follows/{world.paper}", headers=h)
    assert followed.json()["papers"] == [world.paper]
    schema("PaperFollows").validate(followed.json())
    # Following twice changes nothing; unfollowing twice too.
    assert client.put(f"{API_PREFIX}/me/follows/{world.paper}", headers=h).json()["papers"] == [world.paper]
    assert client.delete(f"{API_PREFIX}/me/follows/{world.paper}", headers=h).json()["papers"] == []
    assert client.delete(f"{API_PREFIX}/me/follows/{world.paper}", headers=h).status_code == 200
    off = client.put(f"{API_PREFIX}/me/comment-digest", headers=h, json={"enabled": False})
    assert off.json() == {"papers": [], "commentDigest": False}


def test_only_public_papers_and_existing_accounts(client: TestClient, world: World) -> None:
    h = world.headers(world.reader)
    assert client.put(f"{API_PREFIX}/me/follows/{world.withdrawn}", headers=h).status_code == 404
    assert client.put(f"{API_PREFIX}/me/follows/no-such-paper", headers=h).status_code == 404
    assert client.put(f"{API_PREFIX}/me/follows/{world.paper}", headers=world.headers(world.newbie)).status_code == 403
    assert client.get(f"{API_PREFIX}/me/follows").status_code == 401
    assert client.put(f"{API_PREFIX}/me/comment-digest", headers=h, json={"enabled": "no"}).status_code == 422


def test_commenting_follows_the_paper(client: TestClient, world: World) -> None:
    h = world.headers(world.writer)
    posted = client.post(
        f"{API_PREFIX}/papers/{world.paper}/comments", headers=h, json={"body": "Hi", "anonymous": True}
    )
    assert posted.status_code == 201
    assert client.get(f"{API_PREFIX}/me/follows", headers=h).json()["papers"] == [world.paper]


def test_unsubscribe_links_work_without_signing_in(client: TestClient, world: World) -> None:
    client.put(f"{API_PREFIX}/me/follows/{world.paper}", headers=world.headers(world.reader))
    client.put(f"{API_PREFIX}/me/follows/{world.quiet}", headers=world.headers(world.reader))
    [(token,)] = sql("select digest_token from app.accounts where id = %s", (world.reader,))
    one = client.post(f"{API_PREFIX}/digest/unsubscribe", params={"token": str(token), "paper": world.paper})
    assert one.status_code == 204 and one.headers["Cache-Control"] == "no-store"
    state = client.get(f"{API_PREFIX}/me/follows", headers=world.headers(world.reader)).json()
    assert state == {"papers": [world.quiet], "commentDigest": True}
    assert client.post(f"{API_PREFIX}/digest/unsubscribe", params={"token": str(token)}).status_code == 204
    state = client.get(f"{API_PREFIX}/me/follows", headers=world.headers(world.reader)).json()
    assert state == {"papers": [world.quiet], "commentDigest": False}
    assert client.post(f"{API_PREFIX}/digest/unsubscribe", params={"token": str(uuid.uuid4())}).status_code == 404
    assert client.post(f"{API_PREFIX}/digest/unsubscribe", params={"token": "x"}).status_code == 422


# --- what the digest counts ---------------------------------------------------------------------------------------


def digest_rows(world: World) -> list[tuple[Any, ...]]:
    """What the job sees, read as guthub_api like the job does."""
    since = world.at(0)
    with psycopg.connect(API_DB_URL, autocommit=True) as conn:
        return conn.execute(
            "select account_id, email, paper_id, new_comments from app.comment_digest(%s, %s)"
            " where account_id = any(%s) order by account_id, paper_id",
            (since, since + timedelta(days=1), [world.reader, world.writer]),
        ).fetchall()


def test_the_digest_counts_others_comments_published_that_day(world: World) -> None:
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s), (%s, %s), (%s, %s), (%s, %s)",
        (world.reader, world.paper, world.reader, world.quiet, world.writer, world.paper,
         world.reader, world.withdrawn))  # fmt: skip
    world.comment(world.writer, world.paper, world.at(9))
    world.comment(world.writer, world.paper, world.at(23))
    world.comment(world.writer, world.paper, world.at(0) - timedelta(minutes=1))  # the day before
    world.comment(world.writer, world.paper, world.at(0) + timedelta(days=1))  # the day after
    world.comment(world.writer, world.paper, world.at(10), status="pending")
    world.comment(world.writer, world.paper, world.at(11), status="hidden")
    world.comment(world.writer, world.withdrawn, world.at(12))
    deleted = world.comment(world.writer, world.paper, world.at(13))
    sql("update app.comments set deleted_at = now() where id = %s", (deleted,))
    world.comment(world.reader, world.paper, world.at(14))  # the reader's own comment
    # Each hears about the other's comments on the paper, never their own: the reader about the writer's two, the
    # writer about the reader's one. Nothing for the quiet paper or the withdrawn one.
    assert set(digest_rows(world)) == {
        (world.reader, f"{world.reader}@example.test", world.paper, 2),
        (world.writer, f"{world.writer}@example.test", world.paper, 1),
    }


def test_a_comment_approved_later_counts_on_the_day_it_became_visible(world: World) -> None:
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s)", (world.reader, world.paper))
    cid = world.comment(world.writer, world.paper, world.at(9) - timedelta(days=3), status="pending")
    assert sql("select published_at from app.comments where id = %s", (cid,)) == [(None,)]
    sql("update app.comments set status = 'published' where id = %s", (cid,))
    [(published,)] = sql("select published_at from app.comments where id = %s", (cid,))
    assert published is not None and abs(published - datetime.now(TAIPEI)) < timedelta(minutes=1)
    # Republishing a visible comment does not move it again.
    sql("update app.comments set status = 'published', body = 'edited' where id = %s", (cid,))
    assert sql("select published_at from app.comments where id = %s", (cid,)) == [(published,)]


def test_turning_the_digest_off_or_deleting_the_account_stops_it(world: World) -> None:
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s)", (world.reader, world.paper))
    world.comment(world.writer, world.paper, world.at(9))
    sql("update app.accounts set comment_digest = false where id = %s", (world.reader,))
    assert digest_rows(world) == []
    sql("update app.accounts set comment_digest = true, deleted_at = now() where id = %s", (world.reader,))
    assert digest_rows(world) == []


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_cannot_read_addresses(role: str) -> None:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(pg_sql.SQL("set role {}").format(pg_sql.Identifier(role)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("select * from app.comment_digest(now(), now())")


# --- sending -----------------------------------------------------------------------------------------------------


def test_one_email_per_reader_and_day_naming_nobody(world: World, resend: tuple[str, MockResend]) -> None:
    base, mock = resend
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s), (%s, %s)",
        (world.reader, world.paper, world.reader, world.quiet))  # fmt: skip
    world.comment(world.writer, world.paper, world.at(9))
    world.comment(world.writer, world.paper, world.at(10))
    result = send_digests(API_DB_URL, world.day, ORIGIN, RESEND_KEY, base)
    mine = [r for r in mock.requests if r["body"]["to"] == [f"{world.reader}@example.test"]]
    assert result["failed"] == 0 and len(mine) == 1
    [email] = mine
    assert email["path"] == "/emails" and email["auth"] == f"Bearer {RESEND_KEY}"
    message = email["body"]
    assert message["from"] == "GutHub <no-reply@guthub.tw>"
    assert message["subject"] == "GutHub｜你追蹤的文獻有 2 則新留言"
    assert "Nivo + ipi（Lancet 2026）：2 則新留言" in message["text"]
    assert f"{ORIGIN}/papers/{world.paper}/#comments" in message["text"]
    assert "Quiet" not in message["text"]  # nothing new there
    for part in (message["text"], message["html"]):
        assert "Writer Name" not in part and "comment " not in part
    [(token,)] = sql("select digest_token from app.accounts where id = %s", (world.reader,))
    stop = urlparse(message["headers"]["List-Unsubscribe"].strip("<>"))
    assert stop.path == "/unsubscribe/" and parse_qs(stop.query) == {"t": [str(token)]}
    assert f"paper={world.paper}" in message["text"]
    # The schedule fires again: nothing more is sent.
    again = send_digests(API_DB_URL, world.day, ORIGIN, RESEND_KEY, base)
    assert again["alreadySent"] >= 1
    assert len([r for r in mock.requests if r["body"]["to"] == [f"{world.reader}@example.test"]]) == 1


def test_a_failed_send_is_retried_with_the_same_key(world: World, resend: tuple[str, MockResend]) -> None:
    base, mock = resend
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s)", (world.reader, world.paper))
    world.comment(world.writer, world.paper, world.at(9))
    mock.statuses = [500] * 50  # every send this run fails, including other tests' leftovers on the same day
    assert send_digests(API_DB_URL, world.day, ORIGIN, RESEND_KEY, base)["status"] == "failed"
    assert sql("select sent_at from app.comment_digests where account_id = %s", (world.reader,)) == [(None,)]
    mock.statuses = []
    assert send_digests(API_DB_URL, world.day, ORIGIN, RESEND_KEY, base)["status"] == "sent"
    keys = {r["key"] for r in mock.requests if r["body"]["to"] == [f"{world.reader}@example.test"]}
    assert len(keys) == 1 and next(iter(keys)).startswith("comment-digest/")


def test_dry_run_sends_nothing_and_logs_no_address_or_token(world: World, resend: tuple[str, MockResend]) -> None:
    base, mock = resend
    sql("insert into app.paper_follows (account_id, paper_id) values (%s, %s)", (world.reader, world.paper))
    world.comment(world.writer, world.paper, world.at(9))
    result = send_digests(API_DB_URL, world.day, ORIGIN, None, base)
    assert result["status"] == "dry-run" and result["readers"] >= 1 and mock.requests == []
    [(token,)] = sql("select digest_token from app.accounts where id = %s", (world.reader,))
    logged = json.dumps(result)
    assert "@example.test" not in logged and str(token) not in logged
    assert sql("select 1 from app.comment_digests where account_id = %s", (world.reader,)) == []


def test_the_job_needs_a_key_unless_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", API_DB_URL)
    monkeypatch.delenv("GUTHUB_RESEND_API_KEY", raising=False)
    assert maintenance.main(["comment-digest"]) == 1
    assert maintenance.main(["comment-digest", "--dry-run", "--date", "2001-01-01"]) == 0
