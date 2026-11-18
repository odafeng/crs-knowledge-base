"""The surgeon forum through the API against the real database (H6 #128).

The permission matrix (visitor / signed in without an account / ordinary member / admin who is not a surgeon / verified
surgeon) runs through the API, because ADR-0016 keeps these rules in FastAPI. The app connects as guthub_api. Needs
GUTHUB_TEST_DATABASE_URL; skips without it unless GUTHUB_REQUIRE_DB=1.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from guthub_api.auth import TokenVerifier
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings
from test_comments import API_DB_URL, ISSUER, KEY, World, schema, sql

THREADS = f"{API_PREFIX}/forum/threads"
POSTS = f"{API_PREFIX}/forum/posts"
QUEUE = f"{API_PREFIX}/admin/forum-posts"
ADMIN_THREADS = f"{API_PREFIX}/admin/forum-threads"
MINE = f"{API_PREFIX}/forum/me/posts"


@dataclass
class Forum:
    paper: str
    withdrawn: str
    surgeon: uuid.UUID  # 王醫師, no published posts yet
    peer: uuid.UUID  # 林醫師, another verified surgeon
    member: uuid.UUID  # signed in with an account, not verified
    admin: uuid.UUID  # the maintainer, not a surgeon
    newbie: uuid.UUID  # signed in, no account yet

    def headers(self, user: uuid.UUID | None) -> dict[str, str]:
        return World.headers(self, user)  # pyright: ignore[reportArgumentType]  # signs with test_comments' key


@pytest.fixture
def forum() -> Iterator[Forum]:
    run = uuid.uuid4().hex[:8]
    f = Forum(f"h6-{run}", f"h6-{run}-gone", uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    names = {f.surgeon: "王醫師", f.peer: "林醫師", f.member: "Reader", f.admin: "Maintainer", f.newbie: None}
    sql("insert into app.topics (key, slug, label, title) values ('mCRC-MSI-H', 'msi-h', 'MSI-H', 'MSI-H mCRC')"
        " on conflict do nothing")  # fmt: skip
    for pid, withdrawn in ((f.paper, False), (f.withdrawn, True)):
        sql(
            "insert into app.papers (id, slug, topic_key, year, journal, study_type, regimen, endpoint, result,"
            " bottom_line, source, reviewed_at, detail_html, withdrawn_at) values (%s, %s, 'mCRC-MSI-H', 2024, 'NEJM',"
            " 'Phase 3 RCT', 'Drug', 'OS', 'HR 0.5', 'Use it', 'fulltext', '2026-11-01', '<p>x</p>',"
            " case when %s then now() end)",
            (pid, pid, withdrawn),
        )
    for uid, name in names.items():
        sql("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@example.test"))
        if name:
            sql(
                "insert into app.accounts (id, display_name, is_admin, surgeon_since) values (%s, %s, %s,"
                " case when %s then now() end)",
                (uid, name, uid == f.admin, uid in (f.surgeon, f.peer)),
            )
    yield f
    people = list(names)
    posts = "select id from app.forum_posts where author_id = any(%s)"
    sql(f"delete from app.forum_moderation_events where post_id in ({posts})", (people,))
    sql(f"delete from app.forum_reports where post_id in ({posts})", (people,))
    sql(f"delete from app.forum_posts where thread_id in ({posts})", (people,))
    sql("delete from app.forum_posts where author_id = any(%s)", (people,))
    sql("delete from app.comments where paper_id = any(%s)", ([f.paper, f.withdrawn],))
    sql("delete from app.papers where id = any(%s)", ([f.paper, f.withdrawn],))
    sql("delete from auth.users where id = any(%s)", (people,))


def make_client(**settings: Any) -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL, **settings))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from make_client()


def open_thread(client: TestClient, f: Forum, user: uuid.UUID, **extra: Any) -> dict[str, Any]:
    payload = {"title": "Watch and wait after TNT?", "body": "How long do you follow cCR?", "anonymous": False, **extra}
    response = client.post(THREADS, headers=f.headers(user), json=payload)
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("ForumPostReceipt").validate(response.json())
    return response.json()


def reply(client: TestClient, f: Forum, user: uuid.UUID, thread: str, body: str = "Five years.", **extra: Any) -> Any:
    return client.post(
        f"{THREADS}/{thread}/posts", headers=f.headers(user), json={"body": body, "anonymous": False, **extra}
    )


def moderate(client: TestClient, f: Forum, post: str, action: str = "publish") -> Any:
    return client.patch(f"{QUEUE}/{post}", headers=f.headers(f.admin), json={"action": action, "reason": "checked"})


def published_thread(client: TestClient, f: Forum, user: uuid.UUID, **extra: Any) -> str:
    """A thread members can see: an author's first post is approved, so later ones publish directly."""
    receipt = open_thread(client, f, user, **extra)
    if receipt["status"] == "pending":
        assert moderate(client, f, receipt["id"]).status_code == 200
    return receipt["id"]


def thread_of(client: TestClient, f: Forum, user: uuid.UUID, thread: str) -> dict[str, Any]:
    response = client.get(f"{THREADS}/{thread}", headers=f.headers(user))
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("ForumThreadDetail").validate(response.json())
    return response.json()


def thread_list(client: TestClient, f: Forum, user: uuid.UUID, **params: Any) -> list[dict[str, Any]]:
    response = client.get(THREADS, headers=f.headers(user), params=params)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("ForumThreadPage").validate(response.json())
    return response.json()["items"]


# --- who may enter ----------------------------------------------------------------------------------------------------


def test_everyone_but_verified_surgeons_gets_404_on_every_route(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon)
    routes = [
        ("get", THREADS, None),
        ("post", THREADS, {"title": "t", "body": "b", "anonymous": True}),
        ("get", f"{THREADS}/{thread}", None),
        ("post", f"{THREADS}/{thread}/posts", {"body": "b", "anonymous": True}),
        ("patch", f"{POSTS}/{thread}", {"body": "b"}),
        ("delete", f"{POSTS}/{thread}", None),
        ("put", f"{POSTS}/{thread}/likes", None),
        ("delete", f"{POSTS}/{thread}/likes", None),
        ("post", f"{POSTS}/{thread}/reports", {"reason": "r"}),
        ("get", MINE, None),
    ]
    for user in (None, f.newbie, f.member, f.admin):
        for method, path, body in routes:
            response = client.request(method, path, headers=f.headers(user), json=body)
            assert response.status_code == 404, (user, method, path, response.text)
            assert response.headers["Cache-Control"] == "no-store"
    assert thread_of(client, f, f.peer, thread)["thread"]["id"] == thread

    # Membership is read on every request: a revoked member is out at once, and so is a deleted account.
    sql("update app.accounts set surgeon_since = null where id = %s", (f.peer,))
    assert client.get(f"{THREADS}/{thread}", headers=f.headers(f.peer)).status_code == 404
    sql("update app.accounts set surgeon_since = now(), deleted_at = now() where id = %s", (f.peer,))
    assert client.get(THREADS, headers=f.headers(f.peer)).status_code == 404
    # A bad token is still a session error, not a hidden forum.
    assert client.get(THREADS, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_the_queue_is_for_the_maintainer_only(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon)
    for user in (f.surgeon, f.member):
        assert client.get(QUEUE, headers=f.headers(user)).status_code == 403
        assert client.get(ADMIN_THREADS, headers=f.headers(user)).status_code == 403
        pin = {"pinned": True, "reason": "r"}
        assert client.patch(f"{ADMIN_THREADS}/{thread}", headers=f.headers(user), json=pin).status_code == 403
        reveal = client.post(f"{QUEUE}/{thread}/author", headers=f.headers(user), json={"reason": "r"})
        assert reveal.status_code == 403
    queue = client.get(QUEUE, headers=f.headers(f.admin))
    assert queue.status_code == 200 and queue.headers["Cache-Control"] == "private, no-store"
    schema("ForumModerationItemPage").validate(queue.json())


# --- threads, replies and moderation ----------------------------------------------------------------------------------


def test_first_post_waits_for_the_maintainer_then_later_posts_publish(client: TestClient, forum: Forum) -> None:
    f = forum
    receipt = open_thread(client, f, f.surgeon)
    assert receipt == {"id": receipt["id"], "threadId": receipt["id"], "status": "pending"}
    thread = receipt["id"]
    assert client.get(f"{THREADS}/{thread}", headers=f.headers(f.peer)).status_code == 404
    assert thread not in {t["id"] for t in thread_list(client, f, f.peer)}

    queue = client.get(QUEUE, headers=f.headers(f.admin)).json()
    [item] = [i for i in queue["items"] if i["post"]["id"] == thread]
    assert item["status"] == "pending" and item["post"]["title"] == "Watch and wait after TNT?"
    assert str(f.surgeon) not in str(queue)  # the queue never names the account

    approved = moderate(client, f, thread)
    assert approved.status_code == 200 and approved.json()["status"] == "published"
    assert moderate(client, f, thread).status_code == 409  # nothing left to change
    assert sql("select action, actor_id from app.forum_moderation_events where post_id = %s", (thread,)) == [
        ("publish", f.admin)
    ]
    detail = thread_of(client, f, f.peer, thread)["thread"]
    assert detail["displayName"] == "王醫師" and detail["mine"] is False

    # The author is trusted now: a reply publishes at once. The peer's first reply waits.
    own = reply(client, f, f.surgeon, thread)
    assert own.status_code == 201 and own.json()["status"] == "published"
    first = reply(client, f, f.peer, thread, "Three years with MRI.")
    assert first.json() == {"id": first.json()["id"], "threadId": thread, "status": "pending"}
    replies = thread_of(client, f, f.peer, thread)["replies"]
    assert [r["id"] for r in replies] == [own.json()["id"]]
    summary = next(t for t in thread_list(client, f, f.peer) if t["id"] == thread)
    assert summary["replyCount"] == 1 and summary["lastReplyAt"] is not None


def test_an_approved_paper_comment_counts_as_trust(client: TestClient, forum: Forum) -> None:
    f = forum
    comment = client.post(
        f"{API_PREFIX}/papers/{f.paper}/comments", headers=f.headers(f.peer), json={"body": "x", "anonymous": False}
    ).json()
    sql("update app.comments set status = 'published' where id = %s", (comment["id"],))
    assert open_thread(client, f, f.peer)["status"] == "published"


def test_anonymous_posts_carry_no_author(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon, anonymous=True)
    as_peer = thread_of(client, f, f.peer, thread)
    assert as_peer["thread"]["anonymous"] is True and as_peer["thread"]["displayName"] is None
    assert as_peer["thread"]["mine"] is False
    listing = thread_list(client, f, f.peer)
    for text in (str(as_peer), str(listing)):
        assert str(f.surgeon) not in text and "王醫師" not in text
    assert thread_of(client, f, f.surgeon, thread)["thread"]["mine"] is True
    # The mapping is kept privately, for the author and moderators.
    assert sql("select author_id from app.forum_posts where id = %s", (thread,)) == [(f.surgeon,)]


def test_threads_link_to_topics_and_public_papers(client: TestClient, forum: Forum) -> None:
    f = forum
    linked = published_thread(client, f, f.surgeon, topicKey="mCRC-MSI-H", paperId=f.paper)
    other = open_thread(client, f, f.surgeon, title="Unrelated")["id"]
    detail = thread_of(client, f, f.peer, linked)["thread"]
    assert (detail["topicKey"], detail["paperId"]) == ("mCRC-MSI-H", f.paper)
    by_paper = {t["id"] for t in thread_list(client, f, f.peer, paperId=f.paper)}
    assert linked in by_paper and other not in by_paper
    assert linked in {t["id"] for t in thread_list(client, f, f.peer, topic="mCRC-MSI-H")}

    for bad in ({"paperId": f.withdrawn}, {"paperId": "no-such-paper"}, {"topicKey": "not-a-topic"}):
        payload = {"title": "t", "body": "b", "anonymous": False, **bad}
        assert client.post(THREADS, headers=f.headers(f.surgeon), json=payload).status_code == 422
    # A paper withdrawn later is no longer linked.
    sql("update app.papers set withdrawn_at = now() where id = %s", (f.paper,))
    assert thread_of(client, f, f.peer, linked)["thread"]["paperId"] is None


def test_paging_never_repeats_or_skips(client: TestClient, forum: Forum) -> None:
    f = forum
    made = [published_thread(client, f, f.surgeon, title=f"Thread {i}") for i in range(3)]
    seen: list[str] = []
    cursor = None
    while True:
        response = client.get(
            THREADS, headers=f.headers(f.peer), params={"limit": 1, **({"cursor": cursor} if cursor else {})}
        )
        page = response.json()
        seen += [t["id"] for t in page["items"]]
        if not (cursor := page["nextCursor"]):
            break
    mine = [t for t in seen if t in made]
    assert mine == list(reversed(made)) and len(seen) == len(set(seen))


def test_resends_and_posting_limits(forum: Forum) -> None:
    f = forum
    for client in make_client(comment_burst_limit=2):
        first = open_thread(client, f, f.surgeon)
        assert open_thread(client, f, f.surgeon) == first  # a double submit answers with the first post
        open_thread(client, f, f.surgeon, title="Another")
        limited = client.post(
            THREADS, headers=f.headers(f.surgeon), json={"title": "x", "body": "y", "anonymous": False}
        )
        assert limited.status_code == 429 and int(limited.headers["Retry-After"]) >= 1


def test_only_the_author_edits_or_deletes(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon)
    answer = reply(client, f, f.surgeon, thread).json()["id"]
    assert client.patch(f"{POSTS}/{thread}", headers=f.headers(f.peer), json={"body": "x"}).status_code == 403
    assert client.delete(f"{POSTS}/{thread}", headers=f.headers(f.peer)).status_code == 403

    edited = client.patch(f"{POSTS}/{thread}", headers=f.headers(f.surgeon), json={"body": "Edited", "title": "New"})
    assert edited.status_code == 200
    detail = thread_of(client, f, f.peer, thread)["thread"]
    assert (detail["title"], detail["body"]) == ("New", "Edited")
    titled = client.patch(f"{POSTS}/{answer}", headers=f.headers(f.surgeon), json={"body": "x", "title": "t"})
    assert titled.status_code == 422

    # Deleting the opening post takes the thread and its replies out of view; the rows stay (soft delete).
    assert client.delete(f"{POSTS}/{thread}", headers=f.headers(f.surgeon)).status_code == 204
    assert client.get(f"{THREADS}/{thread}", headers=f.headers(f.peer)).status_code == 404
    assert client.put(f"{POSTS}/{answer}/likes", headers=f.headers(f.peer)).status_code == 404
    assert reply(client, f, f.peer, thread).status_code == 404
    assert sql("select deleted_at is not null from app.forum_posts where id = %s", (thread,)) == [(True,)]


def test_likes_and_reports(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon)
    assert client.put(f"{POSTS}/{thread}/likes", headers=f.headers(f.surgeon)).status_code == 403
    liked = client.put(f"{POSTS}/{thread}/likes", headers=f.headers(f.peer))
    assert liked.status_code == 200 and liked.json() == {"likeCount": 1, "liked": True}
    assert client.put(f"{POSTS}/{thread}/likes", headers=f.headers(f.peer)).json() == {"likeCount": 1, "liked": True}
    assert thread_of(client, f, f.peer, thread)["thread"]["liked"] is True
    as_author = thread_of(client, f, f.surgeon, thread)["thread"]
    assert (as_author["likeCount"], as_author["liked"]) == (1, False)
    assert client.delete(f"{POSTS}/{thread}/likes", headers=f.headers(f.peer)).json() == {
        "likeCount": 0,
        "liked": False,
    }

    assert (
        client.post(f"{POSTS}/{thread}/reports", headers=f.headers(f.surgeon), json={"reason": "x"}).status_code == 403
    )
    report = client.post(
        f"{POSTS}/{thread}/reports", headers=f.headers(f.peer), json={"reason": "Identifiable patient"}
    )
    assert report.status_code == 201
    schema("ForumReportReceipt").validate(report.json())
    assert client.post(f"{POSTS}/{thread}/reports", headers=f.headers(f.peer), json={"reason": "x"}).status_code == 409
    queue = client.get(QUEUE, headers=f.headers(f.admin)).json()
    [item] = [i for i in queue["items"] if i["post"]["id"] == thread]
    assert item["reportCount"] == 1 and item["reports"][0]["reason"] == "Identifiable patient"
    assert str(f.peer) not in str(item)  # nor who reported

    hidden = moderate(client, f, thread, "hide")
    assert hidden.status_code == 200 and hidden.json()["status"] == "hidden"
    assert client.get(f"{THREADS}/{thread}", headers=f.headers(f.peer)).status_code == 404
    assert sql("select resolved_at is not null from app.forum_reports where post_id = %s", (thread,)) == [(True,)]
    actions = sql("select action from app.forum_moderation_events where post_id = %s order by id", (thread,))
    assert [a for (a,) in actions] == ["publish", "hide", "resolve_report"]


# --- H7: pinning, own unpublished posts, author lookup -----------------------------------------------------------------


def test_the_maintainer_pins_threads_to_the_top(client: TestClient, forum: Forum) -> None:
    f = forum
    older = published_thread(client, f, f.surgeon, title="Older")
    published_thread(client, f, f.surgeon, title="Middle")
    newer = published_thread(client, f, f.surgeon, title="Newer")
    pin = client.patch(f"{ADMIN_THREADS}/{older}", headers=f.headers(f.admin), json={"pinned": True, "reason": "FAQ"})
    assert pin.status_code == 200 and pin.headers["Cache-Control"] == "private, no-store"
    schema("ForumPinState").validate(pin.json())
    again = client.patch(f"{ADMIN_THREADS}/{older}", headers=f.headers(f.admin), json={"pinned": True, "reason": "x"})
    assert again.status_code == 409

    page = client.get(THREADS, headers=f.headers(f.peer)).json()
    assert older in [t["id"] for t in page["pinned"]] and older not in [t["id"] for t in page["items"]]
    assert newer in [t["id"] for t in page["items"]]
    assert all(t["pinned"] for t in page["pinned"]) and not any(t["pinned"] for t in page["items"])
    assert thread_of(client, f, f.peer, older)["thread"]["pinned"] is True
    # Pinned threads come on the first page only, so paging neither repeats nor loses them.
    first = client.get(THREADS, headers=f.headers(f.peer), params={"limit": 1}).json()
    assert first["pinned"] and first["nextCursor"]
    later = client.get(THREADS, headers=f.headers(f.peer), params={"cursor": first["nextCursor"]}).json()
    assert later["pinned"] == []

    # A reply cannot be pinned; the admin list shows every thread with its state.
    answer = reply(client, f, f.surgeon, older).json()["id"]
    assert (
        client.patch(
            f"{ADMIN_THREADS}/{answer}", headers=f.headers(f.admin), json={"pinned": True, "reason": "x"}
        ).status_code
        == 404
    )
    listing = client.get(ADMIN_THREADS, headers=f.headers(f.admin))
    schema("ForumAdminThreadPage").validate(listing.json())
    [row] = [i for i in listing.json()["items"] if i["post"]["id"] == older]
    assert row["pinned"] is True and row["replyCount"] == 1 and row["status"] == "published"
    assert str(f.surgeon) not in str(listing.json())

    unpin = client.patch(
        f"{ADMIN_THREADS}/{older}", headers=f.headers(f.admin), json={"pinned": False, "reason": "Old"}
    )
    assert unpin.json() == {"id": older, "pinned": False}
    actions = sql("select action, reason from app.forum_moderation_events where post_id = %s order by id", (older,))
    assert [a for a in actions if a[0] in ("pin", "unpin")] == [("pin", "FAQ"), ("unpin", "Old")]


def test_authors_see_their_own_unpublished_posts(client: TestClient, forum: Forum) -> None:
    f = forum
    waiting = open_thread(client, f, f.surgeon, anonymous=True)["id"]
    page = client.get(MINE, headers=f.headers(f.surgeon))
    assert page.status_code == 200 and page.headers["Cache-Control"] == "private, no-store"
    schema("ForumOwnPostPage").validate(page.json())
    assert [(i["post"]["id"], i["status"]) for i in page.json()["items"]] == [(waiting, "pending")]
    assert client.get(MINE, headers=f.headers(f.peer)).json()["items"] == []  # nobody else's

    assert moderate(client, f, waiting).status_code == 200
    assert client.get(MINE, headers=f.headers(f.surgeon)).json()["items"] == []
    late = reply(client, f, f.peer, waiting, "My first reply").json()["id"]
    [own] = client.get(MINE, headers=f.headers(f.peer)).json()["items"]
    assert own["post"]["id"] == late and own["post"]["threadId"] == waiting and own["status"] == "pending"
    assert moderate(client, f, late, "hide").status_code == 200
    assert client.get(MINE, headers=f.headers(f.peer)).json()["items"][0]["status"] == "hidden"


def test_looking_up_an_anonymous_author_is_recorded(client: TestClient, forum: Forum) -> None:
    f = forum
    thread = published_thread(client, f, f.surgeon, anonymous=True)
    answer = reply(client, f, f.peer, thread, "Reply").json()["id"]
    [item] = [i for i in client.get(QUEUE, headers=f.headers(f.admin)).json()["items"] if i["post"]["id"] == answer]
    assert item["threadTitle"] == "Watch and wait after TNT?"

    path = f"{QUEUE}/{thread}/author"
    assert client.post(path, headers=f.headers(f.admin), json={"reason": " "}).status_code == 422
    found = client.post(path, headers=f.headers(f.admin), json={"reason": "Possible patient details"})
    assert found.status_code == 200 and found.headers["Cache-Control"] == "private, no-store"
    schema("AuthorIdentity").validate(found.json())
    assert found.json() == {"accountId": str(f.surgeon), "displayName": "王醫師"}
    assert sql(
        "select action, reason from app.forum_moderation_events where post_id = %s and action = 'reveal_author'",
        (thread,),
    ) == [("reveal_author", "Possible patient details")]
    unknown = client.post(f"{QUEUE}/{uuid.uuid4()}/author", headers=f.headers(f.admin), json={"reason": "x"})
    assert unknown.status_code == 404


# --- H9: threads opened by GutHub AI ------------------------------------------------------------------------------


def test_ai_threads_are_labelled_and_belong_to_no_one(client: TestClient, forum: Forum) -> None:
    f = forum
    [(thread,)] = sql(
        "insert into app.forum_posts (title, body, anonymous, display_name, ai)"
        " values ('AI opened this', 'Sources on the site.', false, 'GutHub AI', true) returning id"
    )
    thread = str(thread)
    try:
        listed = next(t for t in thread_list(client, f, f.peer) if t["id"] == thread)
        assert listed["ai"] is True and listed["displayName"] == "GutHub AI"
        detail = thread_of(client, f, f.peer, thread)["thread"]
        assert detail["ai"] is True and detail["mine"] is False  # published at once, after the maintainer's review
        own = reply(client, f, f.surgeon, thread).json()["id"]
        assert moderate(client, f, own).status_code == 200  # 王醫師's first post waits, like any other
        assert thread_of(client, f, f.peer, thread)["replies"][0]["ai"] is False
        # Nobody can edit or delete it through the API, and there is no author to look up; likes work as usual.
        assert client.patch(f"{POSTS}/{thread}", headers=f.headers(f.surgeon), json={"body": "x"}).status_code == 403
        assert (
            client.post(f"{QUEUE}/{thread}/author", headers=f.headers(f.admin), json={"reason": "r"}).status_code == 404
        )
        assert client.put(f"{POSTS}/{thread}/likes", headers=f.headers(f.peer)).json()["likeCount"] == 1
    finally:
        sql("delete from app.forum_post_likes where post_id = %s", (thread,))
        sql(
            "delete from app.forum_moderation_events where post_id in"
            " (select id from app.forum_posts where id = %s or thread_id = %s)",
            (thread, thread),
        )
        sql("delete from app.forum_posts where thread_id = %s", (thread,))
        sql("delete from app.forum_posts where id = %s", (thread,))
    assert own
