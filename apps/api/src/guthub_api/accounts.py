"""The signed-in reader's account: public display name and admin role (D1 #67).

An account row is created the first time the reader chooses a display name (ADR-0017: never taken from Google or the
email address). `is_admin` lives only in app.accounts and is set by the maintainer in the database; token claims and
user metadata cannot grant it.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg import errors
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from guthub_api.auth import User, current_user
from guthub_api.db import Conn, get_conn

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Authorization"}

router = APIRouter()
type Db = Annotated[Conn, Depends(get_conn)]
type SignedIn = Annotated[User, Depends(current_user)]
type DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: DisplayName = Field(alias="displayName")


def _account(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {"displayName": None, "isAdmin": False}
    return {"displayName": row["display_name"], "isAdmin": row["is_admin"]}


@router.get("/me")
def get_account(user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    row = db.execute(
        "select display_name, is_admin from app.accounts where id = %s and deleted_at is null", (user.id,)
    ).fetchone()
    return _account(row)


@router.put("/me")
def update_account(update: AccountUpdate, user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    if any(ch < " " or ch == "\x7f" for ch in update.display_name):
        raise HTTPException(status_code=422, detail="Display name cannot contain control characters")
    try:
        row = db.execute(
            "insert into app.accounts (id, display_name) values (%s, %s)"
            " on conflict (id) do update set display_name = excluded.display_name"
            " where app.accounts.deleted_at is null"
            " returning display_name, is_admin",
            (user.id, update.display_name),
        ).fetchone()
    except errors.ForeignKeyViolation as exc:  # the auth user was deleted after the token was issued
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    if row is None:
        raise HTTPException(status_code=409, detail="This account has been deleted")
    return _account(row)


def require_admin(user: SignedIn, db: Db) -> User:
    """For moderation endpoints (D5). The role is read from the database on every request, never from the token."""
    row = db.execute("select is_admin from app.accounts where id = %s and deleted_at is null", (user.id,)).fetchone()
    if row is None or not row["is_admin"]:
        raise HTTPException(status_code=403, detail="Moderator access required")
    return user
