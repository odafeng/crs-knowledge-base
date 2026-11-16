"""Reader comments through the API against the real database (D2 #68).

The permission matrix (visitor / author / other reader / admin) runs here, through the API, because ADR-0016 keeps
these rules in FastAPI only. The app connects as guthub_api. Needs GUTHUB_TEST_DATABASE_URL; skips without it unless
GUTHUB_REQUIRE_DB=1.
"""

import json
import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import jwt
import psycopg
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from guthub_api.auth import TokenVerifier
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "contracts/openapi.yaml").read_text())
DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"

ISSUER = "http://auth.test/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


@dataclass
class World:
    paper: str
    withdrawn: str
    author: uuid.UUID
    other: uuid.UUID
    admin: uuid.UUID
    newbie: uuid.UUID  # signed in, no display name yet

    def newbie_with_name(self) -> uuid.UUID:
        """The newbie, after choosing a name: an account with no comments yet."""
        sql("insert into app.accounts (id, display_name) values (%s, 'Newbie') on conflict do nothing", (self.newbie,))
        return self.newbie

    def headers(self, user: uuid.UUID | None) -> dict[str, str]:
        if user is None:
            return {}
        now = int(time.time())
        claims = {"sub": str(user), "aud": "authenticated", "iss": ISSUER, "role": "authenticated", "iat": now}
        return {"Authorization": f"Bearer {jwt.encode({**claims, 'exp': now + 600}, KEY, algorithm='ES256')}"}


def sql(statement: Any, params: Any = None) -> list[Any]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else []


@pytest.fixture
def world() -> Iterator[World]:
    run = uuid.uuid4().hex[:8]
    w = World(f"d2-{run}", f"d2-{run}-gone", uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    people = {w.author: "Author", w.other: "Other", w.admin: "Admin", w.newbie: None}
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    for pid, withdrawn in ((w.paper, False), (w.withdrawn, True)):
        sql(
            "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result,"
            " bottom_line, source, reviewed_at, detail_html, withdrawn_at) values (%s, %s, 'mCRC-MSI-H', 2024, 'NEJM',"
            " 'Phase 3 RCT', 'Drug', 'OS', 'HR 0.5', 'Use it', 'fulltext', '2026-11-01', '<p>x</p>',"
            " case when %s then now() end)",
            (pid, pid, withdrawn),
        )
    for uid, name in people.items():
        sql("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@example.test"))
        if name:
            sql(
                "insert into app.accounts (id, display_name, is_admin) values (%s, %s, %s)",
                (uid, name, uid == w.admin),
            )
    yield w
    ids = [w.paper, w.withdrawn]
    sql(
        "delete from app.comment_reports where comment_id in (select id from app.comments where paper_id = any(%s))",
        (ids,),
    )
    sql(
        "delete from app.moderation_events where comment_id in (select id from app.comments where paper_id = any(%s))",
        (ids,),
    )
    sql("delete from app.comments where paper_id = any(%s)", (ids,))
    sql("delete from app.papers where id = any(%s)", (ids,))
    sql("delete from auth.users where id = any(%s)", (list(people),))


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


def post(client: TestClient, w: World, user: uuid.UUID | None, body: str = "Useful trial", **extra: Any) -> Any:
    payload = {"body": body, "anonymous": False, **extra}
    return client.post(f"{API_PREFIX}/papers/{w.paper}/comments", headers=w.headers(user), json=payload)


def listed(client: TestClient, w: World, **params: Any) -> Any:
    response = client.get(f"{API_PREFIX}/papers/{w.paper}/comments", params=params)
    assert response.status_code == 200, response.text
    schema("PublicCommentPage").validate(response.json())
    return response.json()


def approve(comment_id: str) -> None:
    """Stands in for moderation (D5)."""
    sql("update app.comments set status = 'published' where id = %s", (comment_id,))


def published(client: TestClient, w: World, user: uuid.UUID, body: str = "Useful trial", **extra: Any) -> str:
    """A comment that is already public: the author's first one is approved, so later ones publish directly."""
    response = post(client, w, user, body, **extra)
    assert response.status_code == 201, response.text
    if response.json()["status"] == "pending":
        approve(response.json()["id"])
    return response.json()["id"]


# --- creating and listing -------------------------------------------------------------------------------------------


def test_first_comment_waits_for_moderation_then_later_ones_publish(client: TestClient, world: World) -> None:
    first = post(client, world, world.author)
    assert first.status_code == 201
    assert first.headers["Cache-Control"] == "private, no-store"
    schema("CommentReceipt").validate(first.json())
    assert first.json()["status"] == "pending"
    assert listed(client, world)["items"] == []

    approve(first.json()["id"])
    second = post(client, world, world.author, "Second thought")
    assert second.json()["status"] == "published"
    assert [c["body"] for c in listed(client, world)["items"]] == ["Useful trial", "Second thought"]


def test_signed_comments_keep_the_name_used_when_posting(client: TestClient, world: World) -> None:
    published(client, world, world.author)
    sql("update app.accounts set display_name = 'Renamed' where id = %s", (world.author,))
    published(client, world, world.author, "After rename")
    names = [c["displayName"] for c in listed(client, world)["items"]]
    assert names == ["Author", "Renamed"]


def test_anonymous_comments_reveal_nothing_about_the_author(client: TestClient, world: World) -> None:
    published(client, world, world.author, "Anonymous view", anonymous=True)
    published(client, world, world.author, "Anonymous again", anonymous=True)
    response = client.get(f"{API_PREFIX}/papers/{world.paper}/comments")
    items = response.json()["items"]
    public = {"id", "paperId", "body", "anonymous", "displayName", "createdAt", "updatedAt", "likeCount"}
    assert all(set(c) == public for c in items)
    assert all(c["anonymous"] is True and c["displayName"] is None for c in items)
    assert str(world.author) not in response.text
    assert "Author" not in response.text and "example.test" not in response.text
    assert len({c["id"] for c in items}) == 2  # ids are per comment, nothing stable links two posts


@pytest.mark.parametrize(
    "payload",
    [
        {"body": "", "anonymous": False},
        {"body": "   \n ", "anonymous": False},
        {"body": "x" * 2001, "anonymous": False},
        {"body": "null\x00byte", "anonymous": False},
        {"body": "bell\x07", "anonymous": False},
        {"body": "ok"},
        {"body": "ok", "anonymous": "yes"},
        {"body": "ok", "anonymous": False, "authorId": "someone"},
        {"body": "ok", "anonymous": False, "status": "published"},
        {"body": "ok", "anonymous": False, "displayName": "Admin"},
    ],
)
def test_invalid_comments_are_rejected(client: TestClient, world: World, payload: dict[str, Any]) -> None:
    response = client.post(
        f"{API_PREFIX}/papers/{world.paper}/comments", headers=world.headers(world.author), json=payload
    )
    assert response.status_code == 422
    schema("Error").validate(response.json())
    assert sql("select count(*) from app.comments where paper_id = %s", (world.paper,))[0][0] == 0


def test_comment_text_is_stored_as_plain_text(client: TestClient, world: World) -> None:
    body = "<script>alert(1)</script>\n第二行 & <b>bold</b>"
    published(client, world, world.author, body)
    published(client, world, world.author, "x" * 2000)
    assert [c["body"] for c in listed(client, world)["items"]] == [body, "x" * 2000]


def test_readers_need_a_display_name_before_commenting(client: TestClient, world: World) -> None:
    for anonymous in (False, True):
        response = post(client, world, world.newbie, anonymous=anonymous)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"


def test_withdrawn_and_unknown_papers_take_no_comments(client: TestClient, world: World) -> None:
    for paper in (world.withdrawn, "no-such-paper"):
        assert client.get(f"{API_PREFIX}/papers/{paper}/comments").status_code == 404
        response = client.post(
            f"{API_PREFIX}/papers/{paper}/comments",
            headers=world.headers(world.author),
            json={"body": "x", "anonymous": False},
        )
        assert response.status_code == 404


def test_comments_hide_with_their_paper(client: TestClient, world: World) -> None:
    published(client, world, world.author)
    sql("update app.papers set withdrawn_at = now() where id = %s", (world.paper,))
    assert client.get(f"{API_PREFIX}/papers/{world.paper}/comments").status_code == 404


def test_reader_comments_are_not_journal_commentary(client: TestClient, world: World) -> None:
    published(client, world, world.author, "Reader opinion")
    paper = client.get(f"{API_PREFIX}/papers/{world.paper}").json()
    assert "Reader opinion" not in json.dumps(paper)
    assert paper["commentary"] == []


def test_listing_pages_through_comments_in_order(client: TestClient, world: World) -> None:
    for i in range(5):
        published(client, world, world.author, f"comment {i}")
    first = listed(client, world, limit=2)
    assert [c["body"] for c in first["items"]] == ["comment 0", "comment 1"]
    # A comment posted between page requests neither repeats nor skips anything.
    published(client, world, world.other, "late arrival")
    second = listed(client, world, limit=2, cursor=first["nextCursor"])
    third = listed(client, world, limit=10, cursor=second["nextCursor"])
    bodies = [c["body"] for page in (first, second, third) for c in page["items"]]
    assert bodies[:5] == [f"comment {i}" for i in range(5)]
    assert third["nextCursor"] is None
    assert client.get(f"{API_PREFIX}/papers/{world.paper}/comments", params={"cursor": "nope"}).status_code == 422


# --- the owner's view ---------------------------------------------------------------------------------------------


def test_owners_see_their_own_comments_with_status(client: TestClient, world: World) -> None:
    pending = post(client, world, world.author, "Mine, waiting").json()["id"]
    published(client, world, world.other, "Someone else's")
    response = client.get(f"{API_PREFIX}/me/comments", headers=world.headers(world.author))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("OwnedCommentPage").validate(response.json())
    assert [(o["comment"]["id"], o["status"]) for o in response.json()["items"]] == [(pending, "pending")]
    assert client.get(f"{API_PREFIX}/me/comments").status_code == 401


# --- the permission matrix ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("who", "status"), [("author", 200), ("other", 403), ("admin", 403), ("visitor", 401)])
def test_only_the_author_can_edit(client: TestClient, world: World, who: str, status: int) -> None:
    comment = published(client, world, world.author, "Original")
    user = None if who == "visitor" else getattr(world, who)
    response = client.patch(f"{API_PREFIX}/comments/{comment}", headers=world.headers(user), json={"body": "Edited"})
    assert response.status_code == status
    body = listed(client, world)["items"][0]
    if status == 200:
        schema("CommentReceipt").validate(response.json())
        assert response.json()["status"] == "published"
        assert body["body"] == "Edited" and body["updatedAt"] > body["createdAt"]
    else:
        assert body["body"] == "Original"


@pytest.mark.parametrize(("who", "status"), [("author", 204), ("other", 403), ("admin", 403), ("visitor", 401)])
def test_only_the_author_can_delete(client: TestClient, world: World, who: str, status: int) -> None:
    comment = published(client, world, world.author)
    user = None if who == "visitor" else getattr(world, who)
    assert client.delete(f"{API_PREFIX}/comments/{comment}", headers=world.headers(user)).status_code == status
    remaining = listed(client, world)["items"]
    assert (remaining == []) == (status == 204)
    if status == 204:
        # Soft delete (ADR-0017): the row stays for 90 days, invisible everywhere, and cannot be touched again.
        assert sql("select deleted_at is not null from app.comments where id = %s", (comment,)) == [(True,)]
        mine = client.get(f"{API_PREFIX}/me/comments", headers=world.headers(world.author)).json()["items"]
        assert comment not in [o["comment"]["id"] for o in mine]
        assert client.delete(f"{API_PREFIX}/comments/{comment}", headers=world.headers(user)).status_code == 404
        patched = client.patch(f"{API_PREFIX}/comments/{comment}", headers=world.headers(user), json={"body": "x"})
        assert patched.status_code == 404


def test_editing_keeps_moderation_state(client: TestClient, world: World) -> None:
    pending = post(client, world, world.author, "Waiting").json()["id"]
    response = client.patch(
        f"{API_PREFIX}/comments/{pending}", headers=world.headers(world.author), json={"body": "Still"}
    )
    assert response.json()["status"] == "pending"
    hidden = published(client, world, world.author, "Rude")
    sql("update app.comments set status = 'hidden' where id = %s", (hidden,))
    response = client.patch(
        f"{API_PREFIX}/comments/{hidden}", headers=world.headers(world.author), json={"body": "Nice"}
    )
    assert response.json()["status"] == "hidden"
    assert listed(client, world)["items"] == []


@pytest.mark.parametrize("comment_id", ["not-a-uuid", str(uuid.uuid4())])
def test_unknown_comments_are_not_found(client: TestClient, world: World, comment_id: str) -> None:
    headers = world.headers(world.author)
    assert client.patch(f"{API_PREFIX}/comments/{comment_id}", headers=headers, json={"body": "x"}).status_code == 404
    assert client.delete(f"{API_PREFIX}/comments/{comment_id}", headers=headers).status_code == 404
    report = client.post(f"{API_PREFIX}/comments/{comment_id}/reports", headers=headers, json={"reason": "spam"})
    assert report.status_code == 404


def test_edits_follow_the_same_body_rules(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author)
    for body in ("", "  ", "x" * 2001, "a\x00b"):
        response = client.patch(
            f"{API_PREFIX}/comments/{comment}", headers=world.headers(world.author), json={"body": body}
        )
        assert response.status_code == 422
    extra = {"body": "ok", "status": "published"}
    assert (
        client.patch(f"{API_PREFIX}/comments/{comment}", headers=world.headers(world.author), json=extra).status_code
        == 422
    )


# --- reports ------------------------------------------------------------------------------------------------------


def test_readers_can_report_a_visible_comment_once(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author)
    url = f"{API_PREFIX}/comments/{comment}/reports"
    first = client.post(url, headers=world.headers(world.other), json={"reason": "  spam  "})
    assert first.status_code == 201
    assert first.headers["Cache-Control"] == "private, no-store"
    schema("ReportReceipt").validate(first.json())
    assert sql("select reason from app.comment_reports where id = %s", (first.json()["id"],)) == [("spam",)]
    assert client.post(url, headers=world.headers(world.other), json={"reason": "again"}).status_code == 409
    assert client.post(url, headers=world.headers(world.admin), json={"reason": "spam"}).status_code == 201


@pytest.mark.parametrize(
    ("who", "payload", "status"),
    [
        ("visitor", {"reason": "spam"}, 401),
        ("newbie", {"reason": "spam"}, 403),
        ("author", {"reason": "spam"}, 403),
        ("other", {"reason": ""}, 422),
        ("other", {"reason": "x" * 1001}, 422),
        ("other", {"reason": "spam", "reporterId": "x"}, 422),
    ],
)
def test_report_rules(client: TestClient, world: World, who: str, payload: dict[str, Any], status: int) -> None:
    comment = published(client, world, world.author)
    user = None if who == "visitor" else getattr(world, who)
    response = client.post(f"{API_PREFIX}/comments/{comment}/reports", headers=world.headers(user), json=payload)
    assert response.status_code == status


def test_hidden_or_pending_comments_cannot_be_reported(client: TestClient, world: World) -> None:
    pending = post(client, world, world.author).json()["id"]
    response = client.post(
        f"{API_PREFIX}/comments/{pending}/reports", headers=world.headers(world.other), json={"reason": "x"}
    )
    assert response.status_code == 404


# --- limits and duplicates (D4 #70) ---------------------------------------------------------------------------------


def backdate(user: uuid.UUID, paper: str, count: int, minutes: int, *, deleted: bool = False) -> None:
    """Comments written `minutes` ago, straight into the table (as an older post would be)."""
    for i in range(count):
        sql(
            "insert into app.comments (paper_id, author_id, body, anonymous, display_name, created_at, updated_at,"
            " deleted_at) values (%s, %s, %s, true, null, now() - %s * interval '1 minute',"
            " now() - %s * interval '1 minute', case when %s then now() end)",
            (paper, user, f"old {minutes} {i}", minutes, minutes, deleted),
        )


def limited_client(**limits: int) -> TestClient:
    app = create_app(Settings(environment="test", database_url=API_DB_URL, **limits))  # pyright: ignore[reportArgumentType]
    client = TestClient(app)
    client.__enter__()
    app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
    return client


def test_a_burst_of_comments_is_limited_with_a_retry_time(client: TestClient, world: World) -> None:
    for i in range(5):
        assert post(client, world, world.author, f"burst {i}").status_code == 201
    response = post(client, world, world.author, "one too many")
    assert response.status_code == 429
    schema("Error").validate(response.json())
    assert response.json()["error"]["code"] == "rate_limited"
    assert 0 < int(response.headers["Retry-After"]) <= 600
    assert response.headers["Cache-Control"] == "no-store"
    assert str(world.author) not in response.text
    # The limit is per account.
    assert post(client, world, world.other, "someone else").status_code == 201


def test_older_comments_leave_the_burst_window(client: TestClient, world: World) -> None:
    backdate(world.author, world.paper, 5, minutes=11)
    assert post(client, world, world.author, "fresh").status_code == 201


def test_deleting_comments_does_not_reset_the_limit(client: TestClient, world: World) -> None:
    backdate(world.author, world.paper, 5, minutes=1, deleted=True)
    assert post(client, world, world.author, "after deleting").status_code == 429


def test_the_daily_limit_counts_the_last_24_hours(world: World) -> None:
    client = limited_client(comment_daily_limit=7)
    try:
        backdate(world.author, world.paper, 6, minutes=120)
        backdate(world.author, world.paper, 10, minutes=60 * 25)  # yesterday: outside the window
        assert post(client, world, world.author, "seventh today").status_code == 201
        response = post(client, world, world.author, "eighth today")
        assert response.status_code == 429
        retry = int(response.headers["Retry-After"])
        assert 22 * 3600 - 60 < retry <= 22 * 3600  # when the oldest of today's comments turns 24 hours old
    finally:
        client.__exit__(None, None, None)


def test_resending_the_same_comment_returns_the_first_one(client: TestClient, world: World) -> None:
    first = post(client, world, world.author, "Same words")
    again = post(client, world, world.author, "Same words")
    assert again.status_code == 201
    assert again.json() == first.json()
    assert sql("select count(*) from app.comments where author_id = %s", (world.author,)) == [(1,)]
    # Different text, identity mode or paper is a new comment; so is the same text after deleting the first.
    assert post(client, world, world.author, "Same words", anonymous=True).json()["id"] != first.json()["id"]
    assert post(client, world, world.author, "Other words").json()["id"] != first.json()["id"]
    client.delete(f"{API_PREFIX}/comments/{first.json()['id']}", headers=world.headers(world.author))
    assert post(client, world, world.author, "Same words").json()["id"] != first.json()["id"]


def test_resends_do_not_use_up_the_limit(client: TestClient, world: World) -> None:
    for _ in range(8):
        assert post(client, world, world.author, "Retried after a timeout").status_code == 201
    assert post(client, world, world.author, "A real second comment").status_code == 201


def test_limits_hold_across_instances_and_concurrent_requests(world: World) -> None:
    from concurrent.futures import ThreadPoolExecutor

    instances = [limited_client(), limited_client()]
    try:
        jobs = [(instances[i % 2], f"concurrent {i}") for i in range(12)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(pool.map(lambda job: post(job[0], world, world.author, job[1]).status_code, jobs))
        assert sorted(codes) == [201] * 5 + [429] * 7
        assert sql("select count(*) from app.comments where author_id = %s", (world.author,)) == [(5,)]
    finally:
        for instance in instances:
            instance.__exit__(None, None, None)


# --- moderation (D5 #71) ------------------------------------------------------------------------------------------


def moderate(
    client: TestClient, w: World, user: uuid.UUID | None, comment: str, action: str, reason: str = "ok"
) -> Any:
    return client.patch(
        f"{API_PREFIX}/admin/comments/{comment}", headers=w.headers(user), json={"action": action, "reason": reason}
    )


def queue(client: TestClient, w: World) -> list[dict[str, Any]]:
    response = client.get(f"{API_PREFIX}/admin/comments", headers=w.headers(w.admin), params={"limit": 100})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("ModerationItemPage").validate(response.json())
    return [item for item in response.json()["items"] if item["comment"]["paperId"] == w.paper]


def events(comment: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in sql(
        "select actor_id, action::text, reason from app.moderation_events where comment_id = %s order by id", (comment,)
    )]  # fmt: skip


def report(client: TestClient, w: World, user: uuid.UUID, comment: str, reason: str = "spam") -> None:
    response = client.post(f"{API_PREFIX}/comments/{comment}/reports", headers=w.headers(user), json={"reason": reason})
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(("who", "status"), [("visitor", 401), ("author", 403), ("newbie", 403), ("admin", 200)])
def test_only_admins_see_the_queue(client: TestClient, world: World, who: str, status: int) -> None:
    user = None if who == "visitor" else getattr(world, who)
    assert client.get(f"{API_PREFIX}/admin/comments", headers=world.headers(user)).status_code == status


def test_queue_holds_pending_and_reported_comments_without_authors(client: TestClient, world: World) -> None:
    pending = post(client, world, world.newbie_with_name(), "First ever", anonymous=True).json()["id"]
    reported = published(client, world, world.author, "Questionable", anonymous=True)
    published(client, world, world.author, "Fine")
    report(client, world, world.other, reported, "misleading dose")
    report(client, world, world.admin, reported, "spam")
    items = {item["comment"]["id"]: item for item in queue(client, world)}
    assert set(items) == {pending, reported}
    assert items[pending]["status"] == "pending" and items[pending]["reportCount"] == 0
    assert items[reported]["reportCount"] == 2
    assert sorted(r["reason"] for r in items[reported]["reports"]) == ["misleading dose", "spam"]
    text = json.dumps(items)
    assert str(world.author) not in text and str(world.other) not in text and "Author" not in text


def test_publishing_a_first_comment_lets_later_ones_through(client: TestClient, world: World) -> None:
    first = post(client, world, world.author, "First").json()["id"]
    response = moderate(client, world, world.admin, first, "publish", "on topic")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("CommentReceipt").validate(response.json())
    assert response.json()["status"] == "published"
    assert events(first) == [(world.admin, "publish", "on topic")]
    assert post(client, world, world.author, "Second").json()["status"] == "published"
    assert first not in [item["comment"]["id"] for item in queue(client, world)]


def test_hiding_removes_a_comment_and_closes_its_reports(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author, "Rude")
    report(client, world, world.other, comment)
    assert moderate(client, world, world.admin, comment, "hide", "personal attack").json()["status"] == "hidden"
    assert listed(client, world)["items"] == []
    assert queue(client, world) == []
    assert sql(
        "select count(*) from app.comment_reports where comment_id = %s and resolved_at is null", (comment,)
    ) == [(0,)]
    assert events(comment) == [
        (world.admin, "hide", "personal attack"),
        (world.admin, "resolve_report", "personal attack"),
    ]
    # Restoring brings it back.
    assert moderate(client, world, world.admin, comment, "publish", "appeal accepted").json()["status"] == "published"
    assert [c["id"] for c in listed(client, world)["items"]] == [comment]


def test_keeping_a_reported_comment_dismisses_the_reports(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author, "Unpopular but fine")
    report(client, world, world.other, comment)
    assert moderate(client, world, world.admin, comment, "publish", "not a violation").status_code == 200
    assert queue(client, world) == []
    assert [c["id"] for c in listed(client, world)["items"]] == [comment]


def test_moderation_conflicts_and_bad_requests(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author)
    assert moderate(client, world, world.admin, comment, "publish").status_code == 409  # nothing to do
    moderate(client, world, world.admin, comment, "hide")
    assert moderate(client, world, world.admin, comment, "hide").status_code == 409
    for body in ({"action": "hide", "reason": " "}, {"action": "delete", "reason": "x"}, {"action": "hide"}):
        response = client.patch(f"{API_PREFIX}/admin/comments/{comment}", headers=world.headers(world.admin), json=body)
        assert response.status_code == 422
    client.delete(f"{API_PREFIX}/comments/{comment}", headers=world.headers(world.author))
    assert moderate(client, world, world.admin, comment, "publish").status_code == 404
    assert moderate(client, world, world.admin, str(uuid.uuid4()), "publish").status_code == 404


@pytest.mark.parametrize("who", ["visitor", "author", "other"])
def test_non_admins_cannot_moderate(client: TestClient, world: World, who: str) -> None:
    comment = post(client, world, world.author, "Waiting").json()["id"]
    user = None if who == "visitor" else getattr(world, who)
    assert moderate(client, world, user, comment, "publish").status_code in (401, 403)
    assert sql("select status::text from app.comments where id = %s", (comment,)) == [("pending",)]
    assert events(comment) == []


def test_revealing_an_anonymous_author_needs_a_reason_and_is_recorded(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author, "Anonymous claim", anonymous=True)
    url = f"{API_PREFIX}/admin/comments/{comment}/author"
    assert client.post(url, headers=world.headers(world.other), json={"reason": "curious"}).status_code == 403
    assert client.post(url, headers=world.headers(world.admin), json={"reason": " "}).status_code == 422
    assert events(comment) == []
    response = client.post(url, headers=world.headers(world.admin), json={"reason": "repeated harassment report"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("AuthorIdentity").validate(response.json())
    assert response.json() == {"accountId": str(world.author), "displayName": "Author"}
    assert events(comment) == [(world.admin, "reveal_author", "repeated harassment report")]
    # After the 90-day purge the mapping is gone and cannot be revealed.
    sql("update app.comments set deleted_at = now(), author_id = null where id = %s", (comment,))
    assert client.post(url, headers=world.headers(world.admin), json={"reason": "again"}).status_code == 404


def test_moderation_never_touches_papers_or_journal_commentary(client: TestClient, world: World) -> None:
    before = client.get(f"{API_PREFIX}/papers/{world.paper}").json()
    comment = published(client, world, world.author)
    moderate(client, world, world.admin, comment, "hide", "spam")
    assert client.get(f"{API_PREFIX}/papers/{world.paper}").json() == before


# --- likes (H1 #123) ----------------------------------------------------------------------------------------------


def like(client: TestClient, w: World, user: uuid.UUID | None, comment: str, method: str = "PUT") -> Any:
    return client.request(method, f"{API_PREFIX}/comments/{comment}/likes", headers=w.headers(user))


def test_readers_like_and_unlike_and_the_list_shows_counts(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author, "Worth reading")
    first = like(client, world, world.other, comment)
    assert first.status_code == 200
    assert first.headers["Cache-Control"] == "private, no-store"
    schema("LikeState").validate(first.json())
    assert first.json() == {"likeCount": 1, "liked": True}
    assert like(client, world, world.other, comment).json() == {"likeCount": 1, "liked": True}  # PUT is idempotent
    assert like(client, world, world.admin, comment).json()["likeCount"] == 2
    assert [c["likeCount"] for c in listed(client, world)["items"]] == [2]
    assert like(client, world, world.other, comment, "DELETE").json() == {"likeCount": 1, "liked": False}
    assert like(client, world, world.other, comment, "DELETE").json() == {"likeCount": 1, "liked": False}
    assert [c["likeCount"] for c in listed(client, world)["items"]] == [1]


def test_each_reader_sees_only_their_own_likes(client: TestClient, world: World) -> None:
    a = published(client, world, world.author, "First")
    b = published(client, world, world.author, "Second")
    like(client, world, world.other, a)
    like(client, world, world.admin, b)
    mine = client.get(f"{API_PREFIX}/me/likes", params={"paperId": world.paper}, headers=world.headers(world.other))
    assert mine.status_code == 200
    assert mine.headers["Cache-Control"] == "private, no-store"
    schema("OwnLikes").validate(mine.json())
    assert mine.json() == {"commentIds": [a]}
    assert client.get(f"{API_PREFIX}/me/likes", params={"paperId": world.paper}).status_code == 401
    # Nothing public says who liked a comment.
    text = client.get(f"{API_PREFIX}/papers/{world.paper}/comments").text
    assert str(world.other) not in text and str(world.admin) not in text


@pytest.mark.parametrize(
    ("who", "status"), [("visitor", 401), ("newbie", 403), ("author", 403), ("other", 200), ("admin", 200)]
)
def test_who_can_like(client: TestClient, world: World, who: str, status: int) -> None:
    comment = published(client, world, world.author, "Anonymous take", anonymous=True)
    user = None if who == "visitor" else getattr(world, who)
    assert like(client, world, user, comment).status_code == status
    expected = 1 if status == 200 else 0
    assert sql("select count(*) from app.comment_likes where comment_id = %s", (comment,)) == [(expected,)]


def test_only_visible_comments_can_be_liked(client: TestClient, world: World) -> None:
    pending = post(client, world, world.author, "Waiting").json()["id"]
    assert like(client, world, world.other, pending).status_code == 404
    hidden = published(client, world, world.author, "Rude")
    sql("update app.comments set status = 'hidden' where id = %s", (hidden,))
    assert like(client, world, world.other, hidden).status_code == 404
    for bad in ("not-a-uuid", str(uuid.uuid4())):
        assert like(client, world, world.other, bad).status_code == 404


def test_likes_survive_on_other_views_and_go_with_deleted_comments(client: TestClient, world: World) -> None:
    comment = published(client, world, world.author, "Liked")
    like(client, world, world.other, comment)
    mine = client.get(f"{API_PREFIX}/me/comments", headers=world.headers(world.author)).json()["items"]
    assert [o["comment"]["likeCount"] for o in mine] == [1]
    client.delete(f"{API_PREFIX}/comments/{comment}", headers=world.headers(world.author))
    assert like(client, world, world.admin, comment).status_code == 404


def test_liking_is_rate_limited(world: World) -> None:
    client = limited_client(comment_like_limit=3)
    try:
        comments = [published(client, world, world.author, f"c{i}") for i in range(4)]
        codes = [like(client, world, world.other, c).status_code for c in comments]
        assert codes == [200, 200, 200, 429]
    finally:
        client.__exit__(None, None, None)


def test_toggling_a_like_cannot_get_around_the_limit(world: World) -> None:
    # Unliking deletes the like, so the limit counts like and unlike events instead of current likes.
    client = limited_client(comment_like_limit=4)
    try:
        comment = published(client, world, world.author, "Toggle me")
        codes = [like(client, world, world.other, comment, method).status_code for method in ["PUT", "DELETE"] * 3]
        # The fifth change is refused, so the sixth (an unlike of a like that never happened) changes nothing and is free.
        assert codes == [200, 200, 200, 200, 429, 200]
        assert like(client, world, world.other, comment).status_code == 429
        # Repeating a request that changes nothing is free.
        state = like(client, world, world.other, comment, "DELETE")
        assert state.status_code == 200
        assert state.json() == {"likeCount": 0, "liked": False}
    finally:
        client.__exit__(None, None, None)


# --- weekly activity (G10 #121) ---------------------------------------------------------------------------------------


def weekly(client: TestClient, w: World, user: uuid.UUID | None = None) -> Any:
    response = client.get(f"{API_PREFIX}/admin/stats/weekly", headers=w.headers(user or w.admin))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    schema("WeeklyActivity").validate(response.json())
    return response.json()


def test_weekly_activity_counts_people_not_actions(client: TestClient, world: World) -> None:
    before = weekly(client, world)
    comment = lambda user, ago: sql(  # noqa: E731
        "insert into app.comments (paper_id, author_id, body, anonymous, created_at)"
        " values (%s, %s, 'x', true, now() - %s * interval '1 day') returning id",
        (world.paper, user, ago),
    )[0][0]
    first = comment(world.author, 0)
    comment(world.author, 0)
    sql("insert into app.comment_likes (comment_id, account_id) values (%s, %s)", (first, world.other))
    sql("insert into app.comment_like_events (account_id) values (%s)", (world.other,))
    sql("insert into app.comment_like_events (account_id, created_at) values (%s, now() - interval '14 days')",
        (world.admin,))  # fmt: skip
    sql("insert into app.comment_reports (comment_id, reporter_id, reason) values (%s, %s, 'r')", (first, world.other))
    after = weekly(client, world)

    assert len(after["weeks"]) == 12 and after["timezone"] == "Asia/Taipei"
    delta = [
        {key: a[key] - b[key] for key in ("activeReaders", "newAccounts", "comments", "likes")}
        for a, b in zip(after["weeks"], before["weeks"], strict=True)
    ]
    # This week: the author (two comments) and the other reader (a like and a report) are two people.
    assert delta[-1] == {"activeReaders": 2, "newAccounts": 0, "comments": 2, "likes": 1}
    assert delta[-3]["activeReaders"] == 1
    assert all(d == dict.fromkeys(d, 0) for d in delta[:-3] + [delta[-2]])
    # Only counts leave the API: no account IDs, names or emails.
    text = json.dumps(after)
    assert all(str(uid) not in text for uid in (world.author, world.other, world.admin))
    assert "Author" not in text and "example.test" not in text
    sql("delete from app.comment_like_events where account_id = any(%s)", ([world.other, world.admin],))


def test_weekly_activity_is_for_the_maintainer_only(client: TestClient, world: World) -> None:
    url = f"{API_PREFIX}/admin/stats/weekly"
    assert client.get(url).status_code == 401
    assert client.get(url, headers=world.headers(world.other)).status_code == 403
