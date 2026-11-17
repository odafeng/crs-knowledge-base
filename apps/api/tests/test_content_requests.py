"""An admin's review and unpublish buttons (E6 #159): the API records the request and starts the job, nothing more.

Runs as guthub_api against the real database like test_accounts.py; skips without GUTHUB_TEST_DATABASE_URL unless
GUTHUB_REQUIRE_DB=1.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
import requests
from fastapi.testclient import TestClient

from guthub_api import content_requests
from guthub_api.auth import TokenVerifier
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings
from test_accounts import API_DB_URL, DB_URL, ISSUER, KEY, bearer, schema, users  # noqa: F401

URL = f"{API_PREFIX}/admin/content-requests"
JOB = "projects/p/locations/r/jobs/content-requests"
BODY = {"action": "review", "kind": "news", "target": "breakwater-os"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL, content_requests_job=JOB))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


@pytest.fixture
def admin(client: TestClient, users: list[uuid.UUID]) -> uuid.UUID:  # noqa: F811
    client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Maintainer"})
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("update app.accounts set is_admin = true where id = %s", (users[0],))
    return users[0]


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake(job: str | None) -> bool:
        calls.append(job or "")
        return True

    monkeypatch.setattr(content_requests, "start_job", fake)
    return calls


def rows(target: str) -> list[tuple[Any, ...]]:
    assert DB_URL
    with psycopg.connect(DB_URL) as conn:
        return conn.execute(
            "select action, kind, requested_by, done_at from app.content_requests where target = %s", (target,)
        ).fetchall()


@pytest.fixture(autouse=True)
def clean() -> Iterator[None]:
    yield
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("delete from app.content_requests where target in ('breakwater-os', 'azur1')")


def test_an_admin_request_is_recorded_and_starts_the_job(
    client: TestClient, admin: uuid.UUID, started: list[str]
) -> None:
    response = client.post(URL, headers=bearer(admin), json=BODY)
    assert response.status_code == 202, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    schema("ContentRequestQueued").validate(response.json())
    assert response.json()["started"] is True
    assert started == [JOB]
    assert rows("breakwater-os") == [("review", "news", admin, None)]


def test_readers_cannot_request_changes(client: TestClient, users: list[uuid.UUID], started: list[str]) -> None:  # noqa: F811
    client.put(f"{API_PREFIX}/me", headers=bearer(users[1]), json={"displayName": "Reader"})
    assert client.post(URL, headers=bearer(users[1]), json=BODY).status_code == 403
    assert client.post(URL, json=BODY).status_code == 401
    assert started == [] and rows("breakwater-os") == []


@pytest.mark.parametrize(
    "body",
    [
        {**BODY, "action": "publish"},
        {**BODY, "kind": "commentary"},
        {**BODY, "target": ""},
        {**BODY, "target": " azur1"},
        {**BODY, "target": "x" * 201},
        {**BODY, "extra": 1},
    ],
)
def test_malformed_requests_are_refused(
    client: TestClient, admin: uuid.UUID, started: list[str], body: dict[str, Any]
) -> None:
    assert client.post(URL, headers=bearer(admin), json=body).status_code == 422
    assert started == []


def test_a_job_that_cannot_start_leaves_the_request_waiting(
    client: TestClient, admin: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_args: Any, **_kwargs: Any) -> Any:
        raise requests.ConnectionError("metadata server unreachable")

    monkeypatch.setattr(content_requests.requests, "get", down)
    response = client.post(URL, headers=bearer(admin), json={**BODY, "action": "unpublish", "target": "azur1"})
    assert response.status_code == 202 and response.json()["started"] is False
    assert rows("azur1") == [("unpublish", "news", admin, None)]


def test_no_job_configured_means_nothing_is_started() -> None:
    assert content_requests.start_job(None) is False
