"""`/me` and the admin role against the real database (D1 #67), plus one round trip through local Supabase Auth.

The app connects as guthub_api, exactly as deployed. Database tests need GUTHUB_TEST_DATABASE_URL; the Auth round trip
also needs GUTHUB_TEST_SUPABASE_URL and GUTHUB_TEST_SERVICE_KEY. Both skip without them unless GUTHUB_REQUIRE_DB=1.
"""

import json
import os
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import jwt
import psycopg
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from guthub_api.accounts import require_admin
from guthub_api.auth import TokenVerifier, User
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "contracts/openapi.yaml").read_text())
DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
REQUIRED = os.environ.get("GUTHUB_REQUIRE_DB") == "1"
if not DB_URL:
    if REQUIRED:
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)
API_DB_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"

ISSUER = "http://auth.test/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


def bearer(user: uuid.UUID, **claims: Any) -> dict[str, str]:
    now = int(time.time())
    payload = {"sub": str(user), "aud": "authenticated", "iss": ISSUER, "role": "authenticated", "iat": now}
    return {"Authorization": f"Bearer {jwt.encode({**payload, 'exp': now + 600, **claims}, KEY, algorithm='ES256')}"}


@pytest.fixture
def users() -> Iterator[list[uuid.UUID]]:
    """Two committed auth users (the API's own connection must see them); removed again afterwards."""
    ids = [uuid.uuid4(), uuid.uuid4()]
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        for uid in ids:
            conn.execute("insert into auth.users (id, email) values (%s, %s)", (uid, f"{uid}@example.test"))
        yield ids
        conn.execute("delete from auth.users where id = any(%s)", (ids,))


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL))  # pyright: ignore[reportArgumentType]

    @app.get(f"{API_PREFIX}/_test/moderate")
    def moderate(user: Annotated[User, Depends(require_admin)]) -> dict[str, str]:
        return {"id": str(user.id)}

    with TestClient(app) as test_client:
        app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
        yield test_client


def me(client: TestClient, user: uuid.UUID, **claims: Any) -> Any:
    response = client.get(f"{API_PREFIX}/me", headers=bearer(user, **claims))
    assert response.headers["Cache-Control"] == "private, no-store"
    return response


def test_new_reader_has_no_display_name_until_choosing_one(client: TestClient, users: list[uuid.UUID]) -> None:
    first = me(client, users[0])
    assert first.status_code == 200
    schema("Account").validate(first.json())
    assert first.json() == {"displayName": None, "isAdmin": False}

    saved = client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "  大腸外科 R1  "})
    assert saved.status_code == 200, saved.text
    assert saved.headers["Cache-Control"] == "private, no-store"
    assert saved.json() == {"displayName": "大腸外科 R1", "isAdmin": False}
    assert me(client, users[0]).json()["displayName"] == "大腸外科 R1"

    renamed = client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Dr. R"})
    assert renamed.json()["displayName"] == "Dr. R"


def test_accounts_are_isolated_between_readers(client: TestClient, users: list[uuid.UUID]) -> None:
    client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "First"})
    assert me(client, users[1]).json() == {"displayName": None, "isAdmin": False}
    client.put(f"{API_PREFIX}/me", headers=bearer(users[1]), json={"displayName": "Second"})
    assert me(client, users[0]).json()["displayName"] == "First"


@pytest.mark.parametrize(
    "body",
    [
        {"displayName": ""},
        {"displayName": "   "},
        {"displayName": "x" * 81},
        {"displayName": "line\nbreak"},
        {"displayName": "ok", "isAdmin": True},
        {"name": "ok"},
    ],
)
def test_invalid_display_names_are_rejected(client: TestClient, users: list[uuid.UUID], body: dict[str, Any]) -> None:
    response = client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json=body)
    assert response.status_code == 422
    schema("Error").validate(response.json())
    assert me(client, users[0]).json() == {"displayName": None, "isAdmin": False}


def test_admin_role_comes_only_from_the_database(client: TestClient, users: list[uuid.UUID]) -> None:
    claims = {"user_metadata": {"is_admin": True}, "app_metadata": {"role": "admin", "is_admin": True}}
    client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Reader"})
    assert me(client, users[0], **claims).json()["isAdmin"] is False
    assert client.get(f"{API_PREFIX}/_test/moderate", headers=bearer(users[0], **claims)).status_code == 403
    assert client.get(f"{API_PREFIX}/_test/moderate", headers=bearer(users[1])).status_code == 403

    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("update app.accounts set is_admin = true where id = %s", (users[0],))
    assert me(client, users[0]).json()["isAdmin"] is True
    assert client.get(f"{API_PREFIX}/_test/moderate", headers=bearer(users[0])).status_code == 200


def test_deleted_accounts_cannot_be_revived(client: TestClient, users: list[uuid.UUID]) -> None:
    client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Gone"})
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("update app.accounts set deleted_at = now() where id = %s", (users[0],))
    assert me(client, users[0]).json() == {"displayName": None, "isAdmin": False}
    assert client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Back"}).status_code == 409


def test_token_for_a_deleted_auth_user_cannot_create_an_account(client: TestClient) -> None:
    response = client.put(f"{API_PREFIX}/me", headers=bearer(uuid.uuid4()), json={"displayName": "Ghost"})
    assert response.status_code == 401


def test_domain_subscriptions_require_display_name_and_preserve_order(
    client: TestClient, users: list[uuid.UUID]
) -> None:
    empty = client.get(f"{API_PREFIX}/me/domains", headers=bearer(users[0]))
    assert empty.status_code == 200
    assert empty.headers["Cache-Control"] == "private, no-store"
    schema("DomainSubscriptions").validate(empty.json())
    assert empty.json() == {"domains": []}

    # Before choosing a display name, saving subscriptions returns 403.
    denied = client.put(
        f"{API_PREFIX}/me/domains",
        headers=bearer(users[0]),
        json={"domains": ["endoscopy"]},
    )
    assert denied.status_code == 403

    client.put(f"{API_PREFIX}/me", headers=bearer(users[0]), json={"displayName": "Surgeon A"})
    saved = client.put(
        f"{API_PREFIX}/me/domains",
        headers=bearer(users[0]),
        json={"domains": ["surgical-intelligence", "endoscopy", "colorectal-oncology"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.headers["Cache-Control"] == "private, no-store"
    schema("DomainSubscriptions").validate(saved.json())
    assert saved.json() == {"domains": ["colorectal-oncology", "endoscopy", "surgical-intelligence"]}

    # Duplicate or unknown domain slugs fail closed with 422.
    assert (
        client.put(
            f"{API_PREFIX}/me/domains",
            headers=bearer(users[0]),
            json={"domains": ["endoscopy", "endoscopy"]},
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"{API_PREFIX}/me/domains",
            headers=bearer(users[0]),
            json={"domains": ["not-a-domain"]},
        ).status_code
        == 422
    )

    # Replacing with empty clears subscriptions cleanly.
    cleared = client.put(f"{API_PREFIX}/me/domains", headers=bearer(users[0]), json={"domains": []})
    assert cleared.status_code == 200 and cleared.json() == {"domains": []}


# --- local Supabase Auth: a real magic-link session, verified through the real JWKS ---------------------------------

AUTH_URL = os.environ.get("GUTHUB_TEST_SUPABASE_URL")
SERVICE_KEY = os.environ.get("GUTHUB_TEST_SERVICE_KEY")


def auth(path: str, body: dict[str, Any] | None = None, method: str = "POST") -> Any:
    assert AUTH_URL and SERVICE_KEY
    request = urllib.request.Request(
        f"{AUTH_URL.rstrip('/')}/auth/v1{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read()
        return json.loads(text) if text else None


@pytest.mark.skipif(not (AUTH_URL and SERVICE_KEY) and not REQUIRED, reason="local Supabase Auth not configured")
def test_a_real_magic_link_session_reaches_the_account() -> None:
    assert AUTH_URL, "GUTHUB_TEST_SUPABASE_URL is required with GUTHUB_REQUIRE_DB=1"
    email = f"d1-{uuid.uuid4().hex[:8]}@example.test"
    user = auth("/admin/users", {"email": email, "email_confirm": True})
    try:
        link = auth("/admin/generate_link", {"type": "magiclink", "email": email})
        hashed = link.get("hashed_token") or link["properties"]["hashed_token"]
        session = auth("/verify", {"type": "email", "token_hash": hashed})
        app = create_app(Settings(environment="test", database_url=API_DB_URL, supabase_url=AUTH_URL))  # pyright: ignore[reportArgumentType]
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {session['access_token']}"}
            assert client.get(f"{API_PREFIX}/me", headers=headers).json() == {"displayName": None, "isAdmin": False}
            saved = client.put(f"{API_PREFIX}/me", headers=headers, json={"displayName": "Magic"})
            assert saved.json()["displayName"] == "Magic"
            tampered = session["access_token"][:-4] + (
                "AAAA" if not session["access_token"].endswith("AAAA") else "BBBB"
            )
            assert client.get(f"{API_PREFIX}/me", headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    finally:
        auth(f"/admin/users/{user['id']}", method="DELETE")
