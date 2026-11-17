"""The signed-in reader's account: public display name, admin role (D1 #67) and followed topics (G6 #117).

An account row is created the first time the reader chooses a display name (ADR-0017: never taken from Google or the
email address). `is_admin` lives only in app.accounts and is set by the maintainer in the database; token claims and
user metadata cannot grant it.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg import errors
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from guthub_api.auth import User, current_user
from guthub_api.content import TOPIC_ORDER, TopicKey
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


# --- followed topics (G6 #117) ----------------------------------------------------------------------------------------


def _distinct(topics: list[str]) -> list[str]:
    if len(set(topics)) != len(topics):
        raise ValueError("topics must not repeat")
    return topics


class TopicSubscriptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    topics: Annotated[list[TopicKey], AfterValidator(_distinct)]


def _topics(db: Conn, user: User) -> dict[str, list[str]]:
    rows = db.execute("select topic_key from app.topic_subscriptions where account_id = %s", (user.id,)).fetchall()
    chosen = {row["topic_key"] for row in rows}
    return {"topics": [key for key in TOPIC_ORDER if key in chosen]}


@router.get("/me/topics")
def get_topics(user: SignedIn, db: Db, response: Response) -> dict[str, list[str]]:
    """The topics this reader follows; private, and never part of a shared page."""
    response.headers.update(PRIVATE)
    return _topics(db, user)


@router.put("/me/topics")
def set_topics(update: TopicSubscriptions, user: SignedIn, db: Db, response: Response) -> dict[str, list[str]]:
    """Replaces the whole set. The account must exist, i.e. the reader has chosen a display name."""
    response.headers.update(PRIVATE)
    with db.transaction():
        account = db.execute(
            "select 1 from app.accounts where id = %s and deleted_at is null for update", (user.id,)
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=403, detail="Choose a display name first")
        db.execute(
            "delete from app.topic_subscriptions where account_id = %s and not (topic_key = any(%s))",
            (user.id, list(update.topics)),
        )
        for key in update.topics:
            db.execute(
                "insert into app.topic_subscriptions (account_id, topic_key) values (%s, %s) on conflict do nothing",
                (user.id, key),
            )
    return _topics(db, user)
