"""Reader comments on papers (D2 #68, ADR-0017).

Comments are plain text in their own table, apart from journal commentary and never part of a paper's evidence. The
public list reads only app.public_comments, which has no author column; signed comments carry the name snapshot taken
when posting. Only the author may edit or delete (soft delete); moderation (approve, hide) is D5. The first comment of
an account waits for moderation, enforced by a database trigger whatever the API sends. Readers can like visible
comments of others (H1); only counts are public. Posting limits and resend\ndetection (D4) run in the database under a per-author lock, so they hold across API instances.
"""

import base64
import binascii
import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from psycopg import errors
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from guthub_api.auth import User, current_user
from guthub_api.db import Conn, get_conn
from guthub_api.settings import Settings

BODY_MAX = 2000  # ADR-0017; the database allows up to 10000 so this can change without a migration
REASON_MAX = 1000
DUPLICATE_MINUTES = 10  # the same text on the same paper within this window is a resend, not a new comment
PUBLIC_CACHE = "public, max-age=30"
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Authorization"}
#: Like count for the comment aliased `c` in a query; who liked it never leaves the database.
LIKE_COUNT = "(select count(*) from app.comment_likes l where l.comment_id = c.id) as like_count"
ALLOWED_CONTROLS = {"\n", "\r", "\t"}

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type SignedIn = Annotated[User, Depends(current_user)]
type Limit = Annotated[int, Query(ge=1, le=100)]
type Cursor = Annotated[str | None, Query()]
type CommentId = Annotated[str, Path()]


def _plain_text(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    if any((ch < " " and ch not in ALLOWED_CONTROLS) or ch == "\x7f" for ch in value):
        raise ValueError("must not contain control characters")
    return value


type Body = Annotated[str, StringConstraints(max_length=BODY_MAX), AfterValidator(_plain_text)]
type Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX), AfterValidator(_plain_text)
]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    body: Body
    anonymous: bool


class CommentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    body: Body


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Reason


# --- helpers ------------------------------------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "paperId": row["paper_id"],
        "body": row["body"],
        "anonymous": row["anonymous"],
        "displayName": row["display_name"],
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
        "likeCount": row["like_count"],
    }


def _receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(row["id"]), "paperId": row["paper_id"], "status": row["status"]}


# Keyset cursor on (created_at, id): comments arrive all the time, and an offset would repeat or skip them.
def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return datetime.fromisoformat(value["t"]), UUID(value["i"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Invalid cursor") from exc


def _encode_cursor(row: dict[str, Any]) -> str:
    raw = json.dumps({"t": row["created_at"].isoformat(), "i": str(row["id"])})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _page(rows: list[dict[str, Any]], limit: int, item: Any) -> dict[str, Any]:
    more = len(rows) > limit
    rows = rows[:limit]
    return {"items": [item(row) for row in rows], "nextCursor": _encode_cursor(rows[-1]) if more else None}


def _require_public_paper(db: Conn, paper_id: str) -> None:
    if db.execute("select 1 from app.public_papers where id = %s", (paper_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Paper not found")


def _display_name(db: Conn, user: User) -> str:
    row = db.execute(
        "select display_name from app.accounts where id = %s and deleted_at is null", (user.id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="Choose a display name before commenting")
    return row["display_name"]


def _own_comment(db: Conn, user: User, comment_id: str) -> None:
    """404 for unknown or deleted comments; 403 when the comment belongs to someone else (including admins)."""
    try:
        uuid = UUID(comment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc
    row = db.execute("select author_id from app.comments where id = %s and deleted_at is null", (uuid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if row["author_id"] != user.id:
        raise HTTPException(status_code=403, detail="Only the author can change this comment")


# --- endpoints ----------------------------------------------------------------------------------------------------


@router.get("/papers/{paper_id}/comments")
def list_comments(
    paper_id: str, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None
) -> dict[str, Any]:
    after = _decode_cursor(cursor)
    _require_public_paper(db, paper_id)
    rows = db.execute(
        "select c.id, c.paper_id, c.body, c.anonymous, c.display_name, c.created_at, c.updated_at, "
        + LIKE_COUNT
        + " from app.public_comments c"
        " where c.paper_id = %s and (%s::timestamptz is null or (c.created_at, c.id) > (%s::timestamptz, %s::uuid))"
        " order by c.created_at, c.id limit %s",
        (paper_id, after and after[0], after and after[0], after and after[1], limit + 1),
    ).fetchall()
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return _page(rows, limit, _public)


@router.post("/papers/{paper_id}/comments", status_code=201)
def create_comment(
    paper_id: str, comment: CommentCreate, user: SignedIn, db: Db, request: Request, response: Response
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _require_public_paper(db, paper_id)
    name = _display_name(db, user)
    settings: Settings = request.app.state.settings
    with db.transaction():
        # One writer per author at a time, on every API instance: the count below cannot race with another post.
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"comments:{user.id}",))
        duplicate = db.execute(
            "select id, paper_id, status from app.comments where author_id = %s and paper_id = %s and body = %s"
            " and anonymous = %s and deleted_at is null and created_at > now() - %s * interval '1 minute'"
            " order by created_at desc limit 1",
            (user.id, paper_id, comment.body, comment.anonymous, DUPLICATE_MINUTES),
        ).fetchone()
        if duplicate is not None:  # a resend after a timeout or a double submit: answer with the first comment
            return _receipt(duplicate)
        _check_limits(db, user, settings)
        row = db.execute(
            "insert into app.comments (paper_id, author_id, body, anonymous, display_name)"
            " values (%s, %s, %s, %s, %s) returning id, paper_id, status",
            (paper_id, user.id, comment.body, comment.anonymous, None if comment.anonymous else name),
        ).fetchone()
    assert row is not None
    return _receipt(row)


def _check_limits(db: Conn, user: User, settings: Settings) -> None:
    """ADR-0017 limits per account. Deleted comments count, so deleting cannot reset the limit."""
    usage = db.execute(
        "select count(*) filter (where created_at > now() - %(burst)s * interval '1 minute') as burst,"
        " ceil(extract(epoch from min(created_at) filter (where created_at > now() - %(burst)s * interval '1 minute')"
        "   + %(burst)s * interval '1 minute' - now())) as burst_retry,"
        " count(*) as day, ceil(extract(epoch from min(created_at) + interval '1 day' - now())) as day_retry"
        " from app.comments where author_id = %(author)s and created_at > now() - interval '1 day'",
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
                detail="Too many comments; try again later",
                headers={"Retry-After": str(max(1, int(retry or 1)))},
            )


@router.get("/me/comments")
def list_own_comments(
    user: SignedIn, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    rows = db.execute(
        "select c.id, c.paper_id, c.body, c.anonymous, c.display_name, c.status, c.created_at, c.updated_at, "
        + LIKE_COUNT
        + " from app.comments c where c.author_id = %s and c.deleted_at is null"
        " and (%s::timestamptz is null or (c.created_at, c.id) > (%s::timestamptz, %s::uuid))"
        " order by c.created_at, c.id limit %s",
        (user.id, after and after[0], after and after[0], after and after[1], limit + 1),
    ).fetchall()
    return _page(rows, limit, lambda row: {"comment": _public(row), "status": row["status"]})


@router.patch("/comments/{comment_id}")
def update_own_comment(
    comment_id: CommentId, update: CommentUpdate, user: SignedIn, db: Db, response: Response
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _own_comment(db, user, comment_id)
    row = db.execute(
        "update app.comments set body = %s, updated_at = now() where id = %s and author_id = %s"
        " and deleted_at is null returning id, paper_id, status",
        (update.body, comment_id, user.id),
    ).fetchone()
    if row is None:  # deleted between the check and the update
        raise HTTPException(status_code=404, detail="Comment not found")
    return _receipt(row)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_own_comment(comment_id: CommentId, user: SignedIn, db: Db, response: Response) -> None:
    response.headers.update(PRIVATE)
    _own_comment(db, user, comment_id)
    db.execute(
        "update app.comments set deleted_at = now() where id = %s and author_id = %s and deleted_at is null",
        (comment_id, user.id),
    )


@router.post("/comments/{comment_id}/reports", status_code=201)
def report_comment(
    comment_id: CommentId, report: ReportCreate, user: SignedIn, db: Db, response: Response
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _display_name(db, user)  # reporting also needs an account
    try:
        uuid = UUID(comment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc
    # Only comments the reader can see are reportable; the private author column is read for the self-check only.
    row = db.execute(
        "select c.author_id from app.public_comments p join app.comments c on c.id = p.id where p.id = %s", (uuid,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if row["author_id"] == user.id:
        raise HTTPException(status_code=403, detail="You cannot report your own comment")
    try:
        created = db.execute(
            "insert into app.comment_reports (comment_id, reporter_id, reason) values (%s, %s, %s) returning id",
            (uuid, user.id, report.reason),
        ).fetchone()
    except errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="You have already reported this comment") from exc
    assert created is not None
    return {"id": str(created["id"]), "commentId": str(uuid)}


# --- likes (H1 #123) ----------------------------------------------------------------------------------------------


def _visible_comment(db: Conn, comment_id: str) -> tuple[UUID, UUID | None]:
    """The comment's ID and private author, if readers can see it; 404 otherwise."""
    try:
        uuid = UUID(comment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc
    row = db.execute(
        "select c.author_id from app.public_comments p join app.comments c on c.id = p.id where p.id = %s", (uuid,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return uuid, row["author_id"]


def _like_state(db: Conn, comment: UUID, user: User) -> dict[str, Any]:
    row = db.execute(
        "select count(*) as likes, coalesce(bool_or(account_id = %s), false) as liked"
        " from app.comment_likes where comment_id = %s",
        (user.id, comment),
    ).fetchone()
    assert row is not None
    return {"likeCount": row["likes"], "liked": row["liked"]}


@router.put("/comments/{comment_id}/likes")
def like_comment(comment_id: CommentId, user: SignedIn, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _display_name(db, user)  # liking needs an account, like posting
    comment, author = _visible_comment(db, comment_id)
    if author == user.id:
        raise HTTPException(status_code=403, detail="You cannot like your own comment")
    settings: Settings = request.app.state.settings
    with db.transaction():
        db.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"likes:{user.id}",))
        already = db.execute(
            "select 1 from app.comment_likes where comment_id = %s and account_id = %s", (comment, user.id)
        ).fetchone()
        if already is None:
            recent = db.execute(
                "select count(*) as n, ceil(extract(epoch from min(created_at)"
                " + %(minutes)s * interval '1 minute' - now())) as retry from app.comment_likes"
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
            db.execute("insert into app.comment_likes (comment_id, account_id) values (%s, %s)", (comment, user.id))
    return _like_state(db, comment, user)


@router.delete("/comments/{comment_id}/likes")
def unlike_comment(comment_id: CommentId, user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    comment, _ = _visible_comment(db, comment_id)
    db.execute("delete from app.comment_likes where comment_id = %s and account_id = %s", (comment, user.id))
    return _like_state(db, comment, user)


@router.get("/me/likes")
def list_own_likes(
    user: SignedIn, db: Db, response: Response, paper_id: Annotated[str, Query(alias="paperId", min_length=1)]
) -> dict[str, Any]:
    """Which visible comments on one paper the reader has liked, so the page can show them pressed."""
    response.headers.update(PRIVATE)
    rows = db.execute(
        "select l.comment_id from app.comment_likes l join app.public_comments p on p.id = l.comment_id"
        " where l.account_id = %s and p.paper_id = %s order by l.created_at",
        (user.id, paper_id),
    ).fetchall()
    return {"commentIds": [str(row["comment_id"]) for row in rows]}
