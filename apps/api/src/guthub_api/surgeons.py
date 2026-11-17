"""Colorectal surgeon membership (H5 #127, ADR-0022): the third tier, which alone may enter the forum.

A signed-in reader applies with their real name, hospital, department and the last three digits of their certificate
number. The maintainer checks these against the public registers (the society's specialist list, or the health
ministry's practitioner lookup for trainees) and approves or rejects; some are approved at once instead
(surgeon_roster.py, H10 #168). Deciding deletes the application: what remains is
app.accounts.surgeon_since and an audit row naming who decided, never the details. Membership is read from the
database on every request; token claims cannot grant it.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from guthub_api.accounts import PRIVATE, require_admin
from guthub_api.auth import User, current_user
from guthub_api.db import Conn, get_conn
from guthub_api.surgeon_roster import RosterSource, check, hospital_of, mail_at

router = APIRouter()

type Db = Annotated[Conn, Depends(get_conn)]
type SignedIn = Annotated[User, Depends(current_user)]
type Admin = Annotated[User, Depends(require_admin)]


def _printable(value: str) -> str:
    if any(ch < " " or ch == "\x7f" for ch in value):
        raise ValueError("must not contain control characters")
    return value


type Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40), AfterValidator(_printable)
]
type Hospital = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80), AfterValidator(_printable)
]


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real_name: Name = Field(alias="realName")
    hospital: Hospital
    department: Name
    # The last three digits of the specialist or physician certificate, ASCII digits only.
    certificate_digits: str = Field(alias="certificateDigits", pattern=r"^[0-9]{3}$")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _status(db: Conn, user: User) -> dict[str, Any]:
    row = db.execute(
        "select a.surgeon_since, (s.account_id is not null) as pending from app.accounts a"
        " left join app.surgeon_applications s on s.account_id = a.id where a.id = %s and a.deleted_at is null",
        (user.id,),
    ).fetchone()
    if row is None:
        return {"status": "none", "since": None}
    if row["surgeon_since"] is not None:
        return {"status": "verified", "since": _iso(row["surgeon_since"])}
    return {"status": "pending" if row["pending"] else "none", "since": None}


@router.get("/me/surgeon")
def get_membership(user: SignedIn, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    return _status(db, user)


@router.put("/me/surgeon", status_code=202)
def apply(application: Application, user: SignedIn, db: Db, request: Request, response: Response) -> dict[str, Any]:
    """Submit, or replace a pending application. The account must exist (a display name was chosen)."""
    response.headers.update(PRIVATE)
    hospital_email = mail_at(user.mailed_email, hospital_of(application.hospital))
    source: RosterSource | None = request.app.state.roster
    # Read before the transaction, and only when approval is possible at all: the map is someone else's server.
    enabled = request.app.state.settings.surgeon_auto_approve
    roster = source.get() if enabled and source and hospital_email else None
    verdict = check(roster, application.real_name, application.hospital, user.mailed_email)
    with db.transaction():
        account = db.execute(
            "select surgeon_since from app.accounts where id = %s and deleted_at is null for update", (user.id,)
        ).fetchone()
        if account is None:
            raise HTTPException(status_code=403, detail="Choose a display name first")
        if account["surgeon_since"] is not None:
            raise HTTPException(status_code=409, detail="Already a verified member")
        # Someone the maintainer once rejected or revoked never gets back in without the maintainer.
        decided_against = db.execute(
            "select 1 from app.surgeon_verification_events where account_id = %s and action in ('reject', 'revoke')",
            (user.id,),
        ).fetchone()
        if verdict.approve and decided_against is None:
            # Decided at once, so like any decision nothing of the application is kept.
            db.execute("delete from app.surgeon_applications where account_id = %s", (user.id,))
            db.execute("update app.accounts set surgeon_since = now() where id = %s", (user.id,))
            db.execute(
                "insert into app.surgeon_verification_events (account_id, action) values (%s, 'auto_approve')",
                (user.id,),
            )
        else:
            db.execute(
                "insert into app.surgeon_applications (account_id, real_name, hospital, department,"
                " certificate_digits, hospital_email) values (%s, %s, %s, %s, %s, %s) on conflict (account_id)"
                " do update set real_name = excluded.real_name, hospital = excluded.hospital,"
                " department = excluded.department, certificate_digits = excluded.certificate_digits,"
                " hospital_email = excluded.hospital_email, submitted_at = now()",
                (user.id, application.real_name, application.hospital, application.department,
                 application.certificate_digits, hospital_email),
            )  # fmt: skip
    return _status(db, user)


@router.delete("/me/surgeon", status_code=204)
def withdraw(user: SignedIn, db: Db, response: Response) -> None:
    """Withdraw a pending application; its details are deleted. A verified membership is not affected."""
    response.headers.update(PRIVATE)
    db.execute("delete from app.surgeon_applications where account_id = %s", (user.id,))


# --- the maintainer ----------------------------------------------------------------------------------------------------


@router.get("/admin/surgeon-applications")
def list_applications(admin: Admin, db: Db, request: Request, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    rows = db.execute(
        "select s.account_id, a.display_name, s.real_name, s.hospital, s.department, s.certificate_digits,"
        " s.submitted_at, s.hospital_email from app.surgeon_applications s join app.accounts a on a.id = s.account_id"
        " where a.deleted_at is null order by s.submitted_at"
    ).fetchall()
    source: RosterSource | None = request.app.state.roster
    roster = source.get() if source and rows else None

    def on_roster(r: Any) -> str:
        listed = check(roster, r["real_name"], r["hospital"], None).listed
        return "unavailable" if listed is None else "listed" if listed else "unlisted"

    return {
        "applications": [
            {
                "accountId": str(r["account_id"]),
                "displayName": r["display_name"],
                "realName": r["real_name"],
                "hospital": r["hospital"],
                "department": r["department"],
                "certificateDigits": r["certificate_digits"],
                "submittedAt": _iso(r["submitted_at"]),
                "hospitalEmail": r["hospital_email"],
                "roster": on_roster(r),
            }
            for r in rows
        ]
    }


@router.post("/admin/surgeon-applications/{account_id}")
def decide(account_id: UUID, decision: Decision, admin: Admin, db: Db, response: Response) -> dict[str, str]:
    """Approve or reject; either way the application and its details are deleted in the same transaction."""
    response.headers.update(PRIVATE)
    with db.transaction():
        removed = db.execute(
            "delete from app.surgeon_applications where account_id = %s returning account_id", (account_id,)
        ).fetchone()
        if removed is None:
            raise HTTPException(status_code=404, detail="No pending application")
        if decision.decision == "approve":
            db.execute("update app.accounts set surgeon_since = now() where id = %s", (account_id,))
        db.execute(
            "insert into app.surgeon_verification_events (account_id, action, decided_by) values (%s, %s, %s)",
            (account_id, decision.decision, admin.id),
        )
    return {"status": "verified" if decision.decision == "approve" else "rejected"}


@router.get("/admin/surgeons")
def list_members(admin: Admin, db: Db, response: Response) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    rows = db.execute(
        "select id, display_name, surgeon_since from app.accounts"
        " where surgeon_since is not null and deleted_at is null order by surgeon_since"
    ).fetchall()
    return {
        "surgeons": [
            {"accountId": str(r["id"]), "displayName": r["display_name"], "since": _iso(r["surgeon_since"])}
            for r in rows
        ]
    }


@router.delete("/admin/surgeons/{account_id}", status_code=204)
def revoke(account_id: UUID, admin: Admin, db: Db, response: Response) -> None:
    response.headers.update(PRIVATE)
    with db.transaction():
        row = db.execute(
            "update app.accounts set surgeon_since = null where id = %s and surgeon_since is not null returning id",
            (account_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Not a verified member")
        db.execute(
            "insert into app.surgeon_verification_events (account_id, action, decided_by) values (%s, 'revoke', %s)",
            (account_id, admin.id),
        )


def require_surgeon(user: SignedIn, db: Db) -> User:
    """For the forum (H6): membership is read from the database on every request, never from the token."""
    row = db.execute(
        "select surgeon_since from app.accounts where id = %s and deleted_at is null", (user.id,)
    ).fetchone()
    if row is None or row["surgeon_since"] is None:
        raise HTTPException(status_code=403, detail="Colorectal surgeon membership required")
    return user
