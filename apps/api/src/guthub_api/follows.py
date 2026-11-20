"""Following papers for the daily comment digest (G8 #119, ADR-0022).

A reader follows a paper with the button on its page, or by commenting on it; either can be undone. Once a day the
comment-digest job (guthub_api.digest) emails each follower how many comments others published on the papers they
follow, never who wrote them. The digest can be turned off from the account page, or without signing in from the
link in every digest, which carries the account's digest token instead of a session.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from guthub_api.auth import User, current_user
from guthub_api.db import Conn, get_conn

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Authorization"}

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type SignedIn = Annotated[User, Depends(current_user)]


class DigestSetting(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


def _account(db: Conn, user: User) -> dict[str, Any]:
    row = db.execute(
        "select comment_digest from app.accounts where id = %s and deleted_at is null", (user.id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="Choose a display name first")
    return row


def _follows(db: Conn, user: User) -> dict[str, Any]:
    account = _account(db, user)
    rows = db.execute(
        "select f.paper_id from app.paper_follows f join app.public_papers p on p.id = f.paper_id"
        " where f.account_id = %s order by f.created_at desc, f.paper_id",
        (user.id,),
    ).fetchall()
    return {"papers": [row["paper_id"] for row in rows], "commentDigest": account["comment_digest"]}


@router.get("/me/follows")
def get_follows(user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    """The papers this reader follows, newest first, and whether the daily digest is on. Private."""
    response.headers.update(PRIVATE)
    return _follows(db, user)


@router.put("/me/follows/{paper_id}")
def follow(paper_id: str, user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _account(db, user)
    if db.execute("select 1 from app.public_papers where id = %s", (paper_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    db.execute(
        "insert into app.paper_follows (account_id, paper_id) values (%s, %s) on conflict do nothing",
        (user.id, paper_id),
    )
    return _follows(db, user)


@router.delete("/me/follows/{paper_id}")
def unfollow(paper_id: str, user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    """Idempotent: unfollowing a paper that is not followed changes nothing."""
    response.headers.update(PRIVATE)
    _account(db, user)
    db.execute("delete from app.paper_follows where account_id = %s and paper_id = %s", (user.id, paper_id))
    return _follows(db, user)


@router.put("/me/comment-digest")
def set_digest(setting: DigestSetting, user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    _account(db, user)
    db.execute("update app.accounts set comment_digest = %s where id = %s", (setting.enabled, user.id))
    return _follows(db, user)


@router.post("/digest/unsubscribe", status_code=204)
def unsubscribe(
    token: Annotated[UUID, Query()], db: Db, response: Response, paper: Annotated[str | None, Query()] = None
) -> None:
    """From a digest's links, without signing in: with `paper`, unfollow that paper; otherwise stop the digest.
    The token is a random value per account that only appears in that account's digests. Unknown tokens answer 404,
    the same as an account that no longer exists, so the endpoint tells nobody which tokens are real beyond that."""
    response.headers["Cache-Control"] = "no-store"
    account = db.execute(
        "select id from app.accounts where digest_token = %s and deleted_at is null", (token,)
    ).fetchone()
    if account is None:
        raise HTTPException(status_code=404, detail="Unknown link")
    if paper is None:
        db.execute("update app.accounts set comment_digest = false where id = %s", (account["id"],))
    else:
        db.execute("delete from app.paper_follows where account_id = %s and paper_id = %s", (account["id"], paper))
