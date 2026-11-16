"""Comment moderation for the maintainer (D5 #71, ADR-0017).

Only accounts with app.accounts.is_admin can use these endpoints (accounts.require_admin). Every action needs a reason
and writes an append-only app.moderation_events record in the same transaction as the change. The queue never shows
who wrote a comment; looking up an anonymous author is a separate, recorded request. Moderation changes only reader
comments, never papers, their review state or journal commentary.

publish: pending -> published, hidden -> published (restore), or published with open reports -> dismiss the reports.
hide:    pending/published -> hidden, or hidden with open reports -> close them.
Either action closes the comment's open reports. A request that would change nothing is a 409.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from guthub_api.accounts import require_admin
from guthub_api.auth import User
from guthub_api.comments import PRIVATE, REASON_MAX, Cursor, Limit, _decode_cursor, _page, _plain_text, _public
from guthub_api.db import Conn, get_conn

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type Admin = Annotated[User, Depends(require_admin)]
type Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REASON_MAX), AfterValidator(_plain_text)
]


class ModerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["publish", "hide"]
    reason: Reason


class AuthorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reason: Reason


def _comment_uuid(comment_id: str) -> UUID:
    try:
        return UUID(comment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Comment not found") from exc


@router.get("/admin/comments")
def list_moderation_queue(admin: Admin, db: Db, response: Response, limit: Limit = 20, cursor: Cursor = None) -> Any:
    """Comments waiting for a first approval or with open reports, oldest first."""
    response.headers.update(PRIVATE)
    after = _decode_cursor(cursor)
    rows = db.execute(
        "select c.id, c.paper_id, c.body, c.anonymous, c.display_name, c.status, c.created_at, c.updated_at,"
        " coalesce(jsonb_agg(jsonb_build_object('reason', r.reason, 'createdAt', r.created_at) order by r.created_at)"
        "   filter (where r.id is not null), '[]') as reports"
        " from app.comments c"
        " left join app.comment_reports r on r.comment_id = c.id and r.resolved_at is null"
        " where c.deleted_at is null"
        " and (%s::timestamptz is null or (c.created_at, c.id) > (%s::timestamptz, %s::uuid))"
        " group by c.id"
        " having c.status = 'pending' or count(r.id) > 0"
        " order by c.created_at, c.id limit %s",
        (after and after[0], after and after[0], after and after[1], limit + 1),
    ).fetchall()

    def item(row: dict[str, Any]) -> dict[str, Any]:
        reports = [{"reason": r["reason"], "createdAt": r["createdAt"].replace("+00:00", "Z")} for r in row["reports"]]
        return {"comment": _public(row), "status": row["status"], "reportCount": len(reports), "reports": reports}

    return _page(rows, limit, item)


@router.patch("/admin/comments/{comment_id}")
def moderate_comment(
    comment_id: str, request: ModerationRequest, admin: Admin, db: Db, response: Response
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    uuid = _comment_uuid(comment_id)
    target = "published" if request.action == "publish" else "hidden"
    with db.transaction():
        row = db.execute(
            "select c.status::text as status, (select count(*) from app.comment_reports r"
            " where r.comment_id = c.id and r.resolved_at is null) as open_reports"
            " from app.comments c where c.id = %s and c.deleted_at is null for update",
            (uuid,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Comment not found")
        if row["status"] == target and row["open_reports"] == 0:
            raise HTTPException(status_code=409, detail=f"Comment is already {target}")
        updated = db.execute(
            "update app.comments set status = %s where id = %s returning id, paper_id, status", (target, uuid)
        ).fetchone()
        db.execute(
            "insert into app.moderation_events (comment_id, actor_id, action, reason) values (%s, %s, %s, %s)",
            (uuid, admin.id, request.action, request.reason),
        )
        if row["open_reports"]:
            db.execute(
                "update app.comment_reports set resolved_at = now() where comment_id = %s and resolved_at is null",
                (uuid,),
            )
            db.execute(
                "insert into app.moderation_events (comment_id, actor_id, action, reason)"
                " values (%s, %s, 'resolve_report', %s)",
                (uuid, admin.id, request.reason),
            )
    assert updated is not None
    return {"id": str(updated["id"]), "paperId": updated["paper_id"], "status": updated["status"]}


@router.post("/admin/comments/{comment_id}/author")
def reveal_author(comment_id: str, request: AuthorRequest, admin: Admin, db: Db, response: Response) -> dict[str, Any]:
    """Who wrote a comment, for handling abuse. Recorded with the reason before anything is returned."""
    response.headers.update(PRIVATE)
    uuid = _comment_uuid(comment_id)
    with db.transaction():
        row = db.execute(
            "select a.id, a.display_name from app.comments c join app.accounts a on a.id = c.author_id where c.id = %s",
            (uuid,),
        ).fetchone()
        if row is None:  # unknown comment, or the mapping was purged 90 days after deletion
            raise HTTPException(status_code=404, detail="No author mapping is kept for this comment")
        db.execute(
            "insert into app.moderation_events (comment_id, actor_id, action, reason)"
            " values (%s, %s, 'reveal_author', %s)",
            (uuid, admin.id, request.reason),
        )
    return {"accountId": str(row["id"]), "displayName": row["display_name"]}
