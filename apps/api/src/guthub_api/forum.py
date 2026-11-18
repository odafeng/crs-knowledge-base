"""The colorectal surgeon forum (H6 #128, ADR-0022): threads, replies, likes, reports and their moderation.

Only verified members may read or write. Everyone else, signed in or not, gets 404 for every forum route, so nothing
reveals whether a thread exists; membership is read from the database on every request. Responses are private and
never shared-cached. The rules are those of reader comments (ADR-0017): a post is signed or anonymous to other members
while the platform keeps the author mapping, the first post of an account waits for the maintainer (a database trigger,
see the migration), authors edit and soft-delete only their own posts, and posting limits and resend detection run in
the database under a per-author lock. A thread is its opening post: hiding or deleting that post hides the thread.
The maintainer pins threads and looks up anonymous authors here too (H7 #129), each action audited with its reason.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from psycopg import errors
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from guthub_api.accounts import require_admin
from guthub_api.auth import User, current_user
from guthub_api.comments import (
    DUPLICATE_MINUTES,
    PRIVATE,
    REASON_MAX,
    Cursor,
    Limit,
    _decode_cursor,
    _iso,
    _page,
    _plain_text,
)
from guthub_api.content import TopicKey
from guthub_api.db import Conn, get_conn
from guthub_api.settings import Settings

BODY_MAX = 5000  # longer than a paper comment: a case discussion needs room. The database allows up to 20000.
TITLE_MAX = 120
NOT_FOUND = HTTPException(status_code=404, detail="Not found")
#: Columns of a post aliased `v` in app.visible_forum_posts, as the member `%(me)s` sees it.
POST_COLUMNS = (
    "v.id, v.thread_id, v.body, v.anonymous, v.display_name, v.created_at, v.updated_at,"
    " (select count(*) from app.forum_post_likes l where l.post_id = v.id) as like_count,"
    " exists (select 1 from app.forum_post_likes l where l.post_id = v.id and l.account_id = %(me)s) as liked,"
    # The private author column is compared with the reader's own ID and never returned.
    " exists (select 1 from app.forum_posts o where o.id = v.id and o.author_id = %(me)s) as mine"
)
#: The linked paper, only while it is public: a withdrawn paper is no longer linked.
PAPER_LINK = "(select pp.id from app.public_papers pp where pp.id = v.paper_id) as paper_id"
#: Visible threads with their counts, filtered by `%(topic)s` and `%(paper)s`; callers add order and paging.
THREAD_SUMMARY = (
    "select v.id, v.title, v.topic_key, " + PAPER_LINK + ", v.anonymous, v.display_name, v.created_at, v.pinned_at,"
    " (select count(*) from app.visible_forum_posts r where r.thread_id = v.id) as reply_count,"
    " (select max(r.created_at) from app.visible_forum_posts r where r.thread_id = v.id) as last_reply_at,"
    " (select count(*) from app.forum_post_likes l where l.post_id = v.id) as like_count"
    " from app.visible_forum_posts v where v.thread_id is null"
    " and (%(topic)s::text is null or v.topic_key = %(topic)s)"
    " and (%(paper)s::text is null or v.paper_id = %(paper)s)"
)

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type Admin = Annotated[User, Depends(require_admin)]
type PostId = Annotated[str, Path()]


def forum_member(request: Request, db: Db) -> User:
    """Verified colorectal surgeons only; anyone else gets the same 404 an unknown thread gets."""
    try:
        user = current_user(request)
    except HTTPException as exc:
        if exc.status_code == 401 and not request.headers.get("Authorization"):
            raise NOT_FOUND from exc
        raise
    row = db.execute(
        "select surgeon_since from app.accounts where id = %s and deleted_at is null", (user.id,)
    ).fetchone()
    if row is None or row["surgeon_since"] is None:
        raise NOT_FOUND
    return user


type Member = Annotated[User, Depends(forum_member)]
type Body = Annotated[str, StringConstraints(max_length=BODY_MAX), AfterValidator(_plain_text)]
type Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX), AfterValidator(_plain_text)
]
type Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX), AfterValidator(_plain_text)
]


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Title
    body: Body
    anonymous: bool
    topic_key: TopicKey | None = Field(default=None, alias="topicKey")
    paper_id: Annotated[str, StringConstraints(min_length=1)] | None = Field(default=None, alias="paperId")


class ReplyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    body: Body
    anonymous: bool


class PostUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    body: Body
    title: Title | None = None


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Reason


class ModerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["publish", "hide"]
    reason: Reason


class PinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pinned: bool
    reason: Reason


class AuthorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Reason


# --- helpers ------------------------------------------------------------------------------------------------------


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise NOT_FOUND from exc


def _post(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "threadId": str(row["thread_id"]) if row["thread_id"] else None,
        "body": row["body"],
        "anonymous": row["anonymous"],
        "displayName": row["display_name"],
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "likeCount": row["like_count"],
        "liked": row["liked"],
        "mine": row["mine"],
    }


def _opening(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **_post(row),
        "title": row["title"],
        "topicKey": row["topic_key"],
        "paperId": row["paper_id"],
        "pinned": row["pinned_at"] is not None,
    }


def _summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "topicKey": row["topic_key"],
        "paperId": row["paper_id"],
        "anonymous": row["anonymous"],
        "displayName": row["display_name"],
        "createdAt": _iso(row["created_at"]),
        "replyCount": row["reply_count"],
        "lastReplyAt": _iso(row["last_reply_at"]) if row["last_reply_at"] else None,
        "likeCount": row["like_count"],
        "pinned": row["pinned_at"] is not None,
    }


def _own_post(row: dict[str, Any]) -> dict[str, Any]:
    """A post as its author or the maintainer sees it outside the thread: with its title, without likes."""
    return {
        "id": str(row["id"]),
        "threadId": str(row["thread_id"]) if row["thread_id"] else None,
        "title": row["title"],
        "body": row["body"],
        "anonymous": row["anonymous"],
        "displayName": row["display_name"],
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
    }


def _receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(row["id"]), "threadId": str(row["thread_id"] or row["id"]), "status": row["status"]}


def _display_name(db: Conn, user: User) -> str:
    row = db.execute("select display_name from app.accounts where id = %s", (user.id,)).fetchone()
    assert row is not None  # forum_member checked the account
    return row["display_name"]


def _check_limits(db: Conn, user: User, settings: Settings) -> None:
    """The comment limits, counted over forum posts. Deleted posts count, so deleting cannot reset them."""
    usage = db.execute(
        "select count(*) filter (where created_at > now() - %(burst)s * interval '1 minute') as burst,"
        " ceil(extract(epoch from min(created_at) filter (where created_at > now() - %(burst)s * interval '1 minute')"
        "   + %(burst)s * interval '1 minute' - now())) as burst_retry,"
        " count(*) as day, ceil(extract(epoch from min(created_at) + interval '1 day' - now())) as day_retry"
        " from app.forum_posts where author_id = %(author)s and created_at > now() - interval '1 day'",
        {"burst": settings.comment_burst_minutes, "author": user.id},
    ).fetchone()
    assert usage is not None
    for count, limit, retry in (
        (usage["burst"], settings.comment_burst_limit, usage["burst_retry"]),
        (usage["day"], settings.comment_daily_limit, usage["day_retry"]),
    ):
        if count >= limit:
            raise HTTPException(
                status_code=429,
                detail="Too many posts; try again later",
                headers={"Retry-After": str(max(1, int(retry or 1)))},
            )


def _create(db: Conn, user: User, settings: Settings, fields: dict[str, Any]) -> dict[str, Any]:
    """Inserts a post, or answers a resend of the same post within DUPLICATE_MINUTES with the first one."""
    name = _display_name(db, user)
    with db.transaction():
        # One writer per author at a time, on every API instance: the count below cannot race with another post.
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"forum:{user.id}",))
        duplicate = db.execute(
            "select id, thread_id, status from app.forum_posts where author_id = %(me)s"
            " and thread_id is not distinct from %(thread_id)s and title is not distinct from %(title)s"
            " and body = %(body)s and anonymous = %(anonymous)s and deleted_at is null"
            " and created_at > now() - %(minutes)s * interval '1 minute' order by created_at desc limit 1",
            {**fields, "me": user.id, "minutes": DUPLICATE_MINUTES},
        ).fetchone()
        if duplicate is not None:
            return _receipt(duplicate)
        _check_limits(db, user, settings)
        row = db.execute(
            "insert into app.forum_posts (thread_id, title, topic_key, paper_id, author_id, body, anonymous,"
            " display_name) values (%(thread_id)s, %(title)s, %(topic_key)s, %(paper_id)s, %(me)s, %(body)s,"
            " %(anonymous)s, %(name)s) returning id, thread_id, status",
            {**fields, "me": user.id, "name": None if fields["anonymous"] else name},
        ).fetchone()
    assert row is not None
    return _receipt(row)


def _visible(db: Conn, post_id: str) -> tuple[UUID, UUID | None]:
    """A post members can see, with its private author for self-checks; 404 otherwise."""
    uuid = _uuid(post_id)
    row = db.execute(
        "select p.author_id from app.visible_forum_posts v join app.forum_posts p on p.id = v.id where v.id = %s",
        (uuid,),
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    return uuid, row["author_id"]


def _own(db: Conn, user: User, post_id: str) -> tuple[UUID, bool]:
    """(post, opens a thread). 404 for unknown or deleted posts; 403 when someone else wrote it."""
    uuid = _uuid(post_id)
    row = db.execute(
        "select author_id, thread_id from app.forum_posts where id = %s and deleted_at is null", (uuid,)
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    if row["author_id"] != user.id:
        raise HTTPException(status_code=403, detail="Only the author can change this post")
    return uuid, row["thread_id"] is None


# --- threads and replies ------------------------------------------------------------------------------------------


@router.get("/forum/threads")
def list_threads(
    member: Member,
    db: Db,
    response: Response,
    limit: Limit = 20,
    cursor: Cursor = None,
    topic: TopicKey | None = None,
    paper_id: Annotated[str | None, Query(alias="paperId", min_length=1)] = None,
) -> dict[str, Any]:
    """Visible threads, newest first. Pinned threads come apart, on the first page only, so paging stays stable."""
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    params = {"topic": topic, "paper": paper_id, "t": after and after[0], "i": after and after[1], "n": limit + 1}
    rows = db.execute(
        THREAD_SUMMARY + " and v.pinned_at is null"
        " and (%(t)s::timestamptz is null or (v.created_at, v.id) < (%(t)s::timestamptz, %(i)s::uuid))"
        " order by v.created_at desc, v.id desc limit %(n)s",
        params,
    ).fetchall()
    pinned = (
        [] if after else db.execute(THREAD_SUMMARY + " and v.pinned_at is not null order by v.pinned_at desc", params)
    )
    return {"pinned": [_summary(row) for row in pinned], **_page(rows, limit, _summary)}


@router.post("/forum/threads", status_code=201)
def create_thread(thread: ThreadCreate, member: Member, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    if thread.paper_id is not None and (
        db.execute("select 1 from app.public_papers where id = %s", (thread.paper_id,)).fetchone() is None
    ):
        raise HTTPException(status_code=422, detail="Unknown paper")
    fields = {
        "thread_id": None,
        "title": thread.title,
        "topic_key": thread.topic_key,
        "paper_id": thread.paper_id,
        "body": thread.body,
        "anonymous": thread.anonymous,
    }
    try:
        return _create(db, member, request.app.state.settings, fields)
    except errors.ForeignKeyViolation as exc:  # a known key whose topic is not in the database yet
        raise HTTPException(status_code=422, detail="Unknown topic") from exc


@router.get("/forum/threads/{thread_id}")
def get_thread(
    thread_id: PostId, member: Member, db: Db, response: Response, limit: Limit = 50, cursor: Cursor = None
) -> dict[str, Any]:
    """The opening post and one page of replies, oldest first."""
    response.headers.update(PRIVATE)
    uuid = _uuid(thread_id)
    after = _decode_cursor(cursor)
    opening = db.execute(
        "select "
        + POST_COLUMNS
        + ", v.title, v.topic_key, v.pinned_at, "
        + PAPER_LINK
        + " from app.visible_forum_posts v"
        " where v.id = %(id)s and v.thread_id is null",
        {"me": member.id, "id": uuid},
    ).fetchone()
    if opening is None:
        raise NOT_FOUND
    rows = db.execute(
        "select " + POST_COLUMNS + " from app.visible_forum_posts v where v.thread_id = %(id)s"
        " and (%(t)s::timestamptz is null or (v.created_at, v.id) > (%(t)s::timestamptz, %(i)s::uuid))"
        " order by v.created_at, v.id limit %(n)s",
        {"me": member.id, "id": uuid, "t": after and after[0], "i": after and after[1], "n": limit + 1},
    ).fetchall()
    page = _page(rows, limit, _post)
    return {"thread": _opening(opening), "replies": page["items"], "nextCursor": page["nextCursor"]}


@router.post("/forum/threads/{thread_id}/posts", status_code=201)
def create_reply(
    thread_id: PostId, reply: ReplyCreate, member: Member, db: Db, request: Request, response: Response
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    uuid = _uuid(thread_id)
    if (
        db.execute("select 1 from app.visible_forum_posts where id = %s and thread_id is null", (uuid,)).fetchone()
        is None
    ):
        raise NOT_FOUND
    fields = {"thread_id": uuid, "title": None, "topic_key": None, "paper_id": None, "body": reply.body,
              "anonymous": reply.anonymous}  # fmt: skip
    return _create(db, member, request.app.state.settings, fields)


@router.get("/forum/me/posts")
def list_own_unpublished(
    member: Member, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None
) -> dict[str, Any]:
    """The member's own posts other members cannot see: waiting for moderation, or hidden. Oldest first."""
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    rows = db.execute(
        "select p.id, p.thread_id, p.title, p.body, p.anonymous, p.display_name, p.status, p.created_at, p.updated_at"
        " from app.forum_posts p where p.author_id = %(me)s and p.deleted_at is null and p.status <> 'published'"
        " and (%(t)s::timestamptz is null or (p.created_at, p.id) > (%(t)s::timestamptz, %(i)s::uuid))"
        " order by p.created_at, p.id limit %(n)s",
        {"me": member.id, "t": after and after[0], "i": after and after[1], "n": limit + 1},
    ).fetchall()
    return _page(rows, limit, lambda row: {"post": _own_post(row), "status": row["status"]})


@router.patch("/forum/posts/{post_id}")
def update_own_post(post_id: PostId, update: PostUpdate, member: Member, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    uuid, opens = _own(db, member, post_id)
    if update.title is not None and not opens:
        raise HTTPException(status_code=422, detail="Only the opening post has a title")
    row = db.execute(
        "update app.forum_posts set body = %s, title = coalesce(%s, title), updated_at = now()"
        " where id = %s and author_id = %s and deleted_at is null returning id, thread_id, status",
        (update.body, update.title, uuid, member.id),
    ).fetchone()
    if row is None:  # deleted between the check and the update
        raise NOT_FOUND
    return _receipt(row)


@router.delete("/forum/posts/{post_id}", status_code=204)
def delete_own_post(post_id: PostId, member: Member, db: Db, response: Response) -> None:
    """Soft delete. Deleting the opening post takes the whole thread out of view."""
    response.headers.update(PRIVATE)
    uuid, _ = _own(db, member, post_id)
    db.execute(
        "update app.forum_posts set deleted_at = now() where id = %s and author_id = %s and deleted_at is null",
        (uuid, member.id),
    )


# --- likes and reports --------------------------------------------------------------------------------------------


def _like_state(db: Conn, post: UUID, user: User) -> dict[str, Any]:
    row = db.execute(
        "select count(*) as likes, coalesce(bool_or(account_id = %s), false) as liked"
        " from app.forum_post_likes where post_id = %s",
        (user.id, post),
    ).fetchone()
    assert row is not None
    return {"likeCount": row["likes"], "liked": row["liked"]}


def _set_like(db: Conn, user: User, post: UUID, *, liked: bool, settings: Settings) -> None:
    """Like or unlike; a change costs one event against the same per-reader budget as comment likes."""
    with db.transaction():
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"likes:{user.id}",))
        has = db.execute(
            "select 1 from app.forum_post_likes where post_id = %s and account_id = %s", (post, user.id)
        ).fetchone()
        if (has is not None) == liked:
            return
        recent = db.execute(
            "select count(*) as n, ceil(extract(epoch from min(created_at)"
            " + %(minutes)s * interval '1 minute' - now())) as retry from app.comment_like_events"
            " where account_id = %(user)s and created_at > now() - %(minutes)s * interval '1 minute'",
            {"user": user.id, "minutes": settings.comment_burst_minutes},
        ).fetchone()
        assert recent is not None
        if recent["n"] >= settings.comment_like_limit:
            raise HTTPException(
                status_code=429,
                detail="Too many likes; try again later",
                headers={"Retry-After": str(max(1, int(recent["retry"] or 1)))},
            )
        if liked:
            db.execute("insert into app.forum_post_likes (post_id, account_id) values (%s, %s)", (post, user.id))
        else:
            db.execute("delete from app.forum_post_likes where post_id = %s and account_id = %s", (post, user.id))
        db.execute("insert into app.comment_like_events (account_id) values (%s)", (user.id,))


@router.put("/forum/posts/{post_id}/likes")
def like_post(post_id: PostId, member: Member, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    post, author = _visible(db, post_id)
    if author == member.id:
        raise HTTPException(status_code=403, detail="You cannot like your own post")
    _set_like(db, member, post, liked=True, settings=request.app.state.settings)
    return _like_state(db, post, member)


@router.delete("/forum/posts/{post_id}/likes")
def unlike_post(post_id: PostId, member: Member, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    post, _ = _visible(db, post_id)
    _set_like(db, member, post, liked=False, settings=request.app.state.settings)
    return _like_state(db, post, member)


@router.post("/forum/posts/{post_id}/reports", status_code=201)
def report_post(post_id: PostId, report: ReportCreate, member: Member, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    post, author = _visible(db, post_id)
    if author == member.id:
        raise HTTPException(status_code=403, detail="You cannot report your own post")
    try:
        created = db.execute(
            "insert into app.forum_reports (post_id, reporter_id, reason) values (%s, %s, %s) returning id",
            (post, member.id, report.reason),
        ).fetchone()
    except errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="You have already reported this post") from exc
    assert created is not None
    return {"id": str(created["id"]), "postId": str(post)}


# --- the maintainer -----------------------------------------------------------------------------------------------


@router.get("/admin/forum-posts")
def list_forum_queue(admin: Admin, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> Any:
    """Posts waiting for a first approval or with open reports, oldest first. Authors are never shown."""
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    rows = db.execute(
        "select p.id, p.thread_id, p.title, p.body, p.anonymous, p.display_name, p.status, p.created_at,"
        " p.updated_at, (select t.title from app.forum_posts t where t.id = p.thread_id) as thread_title,"
        " coalesce(jsonb_agg(jsonb_build_object('reason', r.reason, 'createdAt', r.created_at)"
        "   order by r.created_at) filter (where r.id is not null), '[]') as reports"
        " from app.forum_posts p"
        " left join app.forum_reports r on r.post_id = p.id and r.resolved_at is null"
        " where p.deleted_at is null"
        " and (%s::timestamptz is null or (p.created_at, p.id) > (%s::timestamptz, %s::uuid))"
        " group by p.id having p.status = 'pending' or count(r.id) > 0"
        " order by p.created_at, p.id limit %s",
        (after and after[0], after and after[0], after and after[1], limit + 1),
    ).fetchall()

    def item(row: dict[str, Any]) -> dict[str, Any]:
        reports = [{"reason": r["reason"], "createdAt": r["createdAt"].replace("+00:00", "Z")} for r in row["reports"]]
        return {
            "post": _own_post(row),
            "threadTitle": row["thread_title"],
            "status": row["status"],
            "reportCount": len(reports),
            "reports": reports,
        }

    return _page(rows, limit, item)


@router.patch("/admin/forum-posts/{post_id}")
def moderate_post(
    post_id: PostId, request: ModerationRequest, admin: Admin, db: Db, response: Response
) -> dict[str, Any]:
    """Same rules as comment moderation: publish or hide, both close open reports, and every action is audited."""
    response.headers.update(PRIVATE)
    uuid = _uuid(post_id)
    target = "published" if request.action == "publish" else "hidden"
    with db.transaction():
        row = db.execute(
            "select p.status::text as status, (select count(*) from app.forum_reports r"
            " where r.post_id = p.id and r.resolved_at is null) as open_reports"
            " from app.forum_posts p where p.id = %s and p.deleted_at is null for update",
            (uuid,),
        ).fetchone()
        if row is None:
            raise NOT_FOUND
        if row["status"] == target and row["open_reports"] == 0:
            raise HTTPException(status_code=409, detail=f"Post is already {target}")
        updated = db.execute(
            "update app.forum_posts set status = %s where id = %s returning id, thread_id, status", (target, uuid)
        ).fetchone()
        db.execute(
            "insert into app.forum_moderation_events (post_id, actor_id, action, reason) values (%s, %s, %s, %s)",
            (uuid, admin.id, request.action, request.reason),
        )
        if row["open_reports"]:
            db.execute(
                "update app.forum_reports set resolved_at = now() where post_id = %s and resolved_at is null", (uuid,)
            )
            db.execute(
                "insert into app.forum_moderation_events (post_id, actor_id, action, reason)"
                " values (%s, %s, 'resolve_report', %s)",
                (uuid, admin.id, request.reason),
            )
    assert updated is not None
    return _receipt(updated)


@router.post("/admin/forum-posts/{post_id}/author")
def reveal_post_author(
    post_id: PostId, request: AuthorRequest, admin: Admin, db: Db, response: Response
) -> dict[str, Any]:
    """Who wrote a post, for handling abuse. Recorded with the reason before anything is returned."""
    response.headers.update(PRIVATE)
    uuid = _uuid(post_id)
    with db.transaction():
        row = db.execute(
            "select a.id, a.display_name from app.forum_posts p join app.accounts a on a.id = p.author_id"
            " where p.id = %s",
            (uuid,),
        ).fetchone()
        if row is None:  # unknown post, or the mapping was purged 90 days after deletion
            raise HTTPException(status_code=404, detail="No author mapping is kept for this post")
        db.execute(
            "insert into app.forum_moderation_events (post_id, actor_id, action, reason)"
            " values (%s, %s, 'reveal_author', %s)",
            (uuid, admin.id, request.reason),
        )
    return {"accountId": str(row["id"]), "displayName": row["display_name"]}


@router.get("/admin/forum-threads")
def list_all_threads(admin: Admin, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> Any:
    """Every thread that is not deleted, whatever its status, newest first: what the maintainer pins or hides."""
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    rows = db.execute(
        "select p.id, p.thread_id, p.title, p.body, p.anonymous, p.display_name, p.status, p.created_at, p.updated_at,"
        " p.pinned_at, (select count(*) from app.visible_forum_posts r where r.thread_id = p.id) as reply_count"
        " from app.forum_posts p where p.thread_id is null and p.deleted_at is null"
        " and (%(t)s::timestamptz is null or (p.created_at, p.id) < (%(t)s::timestamptz, %(i)s::uuid))"
        " order by p.created_at desc, p.id desc limit %(n)s",
        {"t": after and after[0], "i": after and after[1], "n": limit + 1},
    ).fetchall()
    return _page(
        rows,
        limit,
        lambda row: {
            "post": _own_post(row),
            "status": row["status"],
            "pinned": row["pinned_at"] is not None,
            "replyCount": row["reply_count"],
        },
    )


@router.patch("/admin/forum-threads/{thread_id}")
def pin_thread(thread_id: PostId, request: PinRequest, admin: Admin, db: Db, response: Response) -> dict[str, Any]:
    """Pin or unpin a thread, with a recorded reason. A request that changes nothing is a 409."""
    response.headers.update(PRIVATE)
    uuid = _uuid(thread_id)
    with db.transaction():
        row = db.execute(
            "select pinned_at from app.forum_posts where id = %s and thread_id is null and deleted_at is null for update",
            (uuid,),
        ).fetchone()
        if row is None:
            raise NOT_FOUND
        if (row["pinned_at"] is not None) == request.pinned:
            raise HTTPException(
                status_code=409, detail=f"Thread is already {'pinned' if request.pinned else 'unpinned'}"
            )
        db.execute(
            "update app.forum_posts set pinned_at = case when %s then now() end where id = %s", (request.pinned, uuid)
        )
        db.execute(
            "insert into app.forum_moderation_events (post_id, actor_id, action, reason) values (%s, %s, %s, %s)",
            (uuid, admin.id, "pin" if request.pinned else "unpin", request.reason),
        )
    return {"id": str(uuid), "pinned": request.pinned}
