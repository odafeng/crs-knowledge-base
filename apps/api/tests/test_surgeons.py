"""Colorectal surgeon membership (H5 #127): apply, decide, revoke, and what is kept afterwards.

Runs as guthub_api against the real database like test_accounts.py; skips without GUTHUB_TEST_DATABASE_URL unless
GUTHUB_REQUIRE_DB=1.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import psycopg
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from guthub_api.auth import TokenVerifier, User
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings
from guthub_api.surgeons import require_surgeon
from test_accounts import API_DB_URL, DB_URL, ISSUER, KEY, bearer, schema, users  # noqa: F401

ME = f"{API_PREFIX}/me/surgeon"
APPLICATIONS = f"{API_PREFIX}/admin/surgeon-applications"
MEMBERS = f"{API_PREFIX}/admin/surgeons"
FORM = {"realName": "王小明", "hospital": "某醫學中心", "department": "大腸直腸外科", "certificateDigits": "042"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL))  # pyright: ignore[reportArgumentType]

    @app.get(f"{API_PREFIX}/_test/forum")
    def forum(user: Annotated[User, Depends(require_surgeon)]) -> dict[str, str]:
        return {"id": str(user.id)}

    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


@pytest.fixture
def people(client: TestClient, users: list[uuid.UUID]) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: F811
    """(admin, applicant), both with display names."""
    admin, applicant = users
    client.put(f"{API_PREFIX}/me", headers=bearer(admin), json={"displayName": "Maintainer"})
    client.put(f"{API_PREFIX}/me", headers=bearer(applicant), json={"displayName": "R2"})
    sql("update app.accounts set is_admin = true where id = %s", admin)
    return admin, applicant


def sql(statement: str, *params: Any) -> list[tuple[Any, ...]]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cursor = conn.execute(statement, params)  # pyright: ignore[reportArgumentType]
        return cursor.fetchall() if cursor.description else []


def status(client: TestClient, user: uuid.UUID) -> dict[str, Any]:
    response = client.get(ME, headers=bearer(user))
    assert response.status_code == 200 and response.headers["Cache-Control"] == "private, no-store"
    schema("SurgeonMembership").validate(response.json())
    return response.json()


def test_apply_approve_and_revoke(client: TestClient, people: tuple[uuid.UUID, uuid.UUID]) -> None:
    admin, applicant = people
    assert status(client, applicant) == {"status": "none", "since": None}
    assert client.get(f"{API_PREFIX}/_test/forum", headers=bearer(applicant)).status_code == 403

    applied = client.put(ME, headers=bearer(applicant), json=FORM)
    assert applied.status_code == 202, applied.text
    assert applied.json() == {"status": "pending", "since": None}

    assert client.get(APPLICATIONS, headers=bearer(applicant)).status_code == 403  # readers never see the queue
    queue = client.get(APPLICATIONS, headers=bearer(admin))
    schema("SurgeonApplicationList").validate(queue.json())
    [entry] = [a for a in queue.json()["applications"] if a["accountId"] == str(applicant)]
    assert entry | {"submittedAt": None} == {
        **FORM,
        "accountId": str(applicant),
        "displayName": "R2",
        "submittedAt": None,
    }

    decided = client.post(f"{APPLICATIONS}/{applicant}", headers=bearer(admin), json={"decision": "approve"})
    assert decided.status_code == 200 and decided.json() == {"status": "verified"}
    assert status(client, applicant)["status"] == "verified"
    assert client.get(f"{API_PREFIX}/_test/forum", headers=bearer(applicant)).status_code == 200
    # Deciding deletes the details; the audit names who decided and nothing else.
    assert sql("select 1 from app.surgeon_applications where account_id = %s", applicant) == []
    assert sql("select action, decided_by from app.surgeon_verification_events where account_id = %s", applicant) == [
        ("approve", admin)
    ]
    assert client.put(ME, headers=bearer(applicant), json=FORM).status_code == 409

    members = client.get(MEMBERS, headers=bearer(admin)).json()
    schema("SurgeonMemberList").validate(members)
    assert str(applicant) in {m["accountId"] for m in members["surgeons"]}

    assert client.delete(f"{MEMBERS}/{applicant}", headers=bearer(admin)).status_code == 204
    assert status(client, applicant)["status"] == "none"
    assert client.get(f"{API_PREFIX}/_test/forum", headers=bearer(applicant)).status_code == 403
    assert client.delete(f"{MEMBERS}/{applicant}", headers=bearer(admin)).status_code == 404
    actions = sql("select action from app.surgeon_verification_events where account_id = %s order by id", applicant)
    assert [a for (a,) in actions] == ["approve", "revoke"]


def test_rejecting_deletes_the_details(client: TestClient, people: tuple[uuid.UUID, uuid.UUID]) -> None:
    admin, applicant = people
    client.put(ME, headers=bearer(applicant), json=FORM)
    rejected = client.post(f"{APPLICATIONS}/{applicant}", headers=bearer(admin), json={"decision": "reject"})
    assert rejected.json() == {"status": "rejected"}
    assert status(client, applicant)["status"] == "none"
    assert sql("select 1 from app.surgeon_applications where account_id = %s", applicant) == []
    assert (
        client.post(f"{APPLICATIONS}/{applicant}", headers=bearer(admin), json={"decision": "approve"}).status_code
        == 404
    )


def test_withdrawing_deletes_the_details(client: TestClient, people: tuple[uuid.UUID, uuid.UUID]) -> None:
    _, applicant = people
    client.put(ME, headers=bearer(applicant), json=FORM)
    assert client.put(ME, headers=bearer(applicant), json={**FORM, "hospital": "另一家醫院"}).status_code == 202
    assert sql("select hospital from app.surgeon_applications where account_id = %s", applicant) == [("另一家醫院",)]
    assert client.delete(ME, headers=bearer(applicant)).status_code == 204
    assert status(client, applicant)["status"] == "none"
    assert sql("select 1 from app.surgeon_applications where account_id = %s", applicant) == []


def test_a_display_name_comes_first(client: TestClient, users: list[uuid.UUID]) -> None:  # noqa: F811
    assert client.put(ME, headers=bearer(users[1]), json=FORM).status_code == 403
    assert client.put(ME, json=FORM).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"certificateDigits": "12a"},
        {"certificateDigits": "1234"},
        {"certificateDigits": "１２３"},  # full-width digits are not the ASCII digits the form asks for
        {"realName": ""},
        {"realName": "王\x00小明"},
        {"hospital": "x" * 81},
        {"nationalId": "A123456789"},  # never accepted, even if a client sends it
    ],
)
def test_malformed_applications_are_refused(
    client: TestClient, people: tuple[uuid.UUID, uuid.UUID], change: dict[str, str]
) -> None:
    assert client.put(ME, headers=bearer(people[1]), json={**FORM, **change}).status_code == 422


def test_deleting_the_account_drops_membership_and_application(
    client: TestClient, people: tuple[uuid.UUID, uuid.UUID]
) -> None:
    admin, applicant = people
    client.put(ME, headers=bearer(applicant), json=FORM)
    client.post(f"{APPLICATIONS}/{applicant}", headers=bearer(admin), json={"decision": "approve"})
    client.put(ME, headers=bearer(admin), json=FORM)  # an admin can apply too; this one stays pending
    sql("update app.accounts set deleted_at = now() where id = any(%s)", [admin, applicant])
    assert sql("select surgeon_since from app.accounts where id = %s", applicant) == [(None,)]
    assert sql("select 1 from app.surgeon_applications where account_id = %s", admin) == []
