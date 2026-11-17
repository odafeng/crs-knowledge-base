"""Access-token verification (D1 #67), with locally generated keys standing in for the Supabase JWKS."""

import base64
import json
import time
import uuid
from typing import Annotated, Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from guthub_api.auth import TokenVerifier, User, current_user
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

ISSUER = "http://auth.test/auth/v1"
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
USER = uuid.uuid4()


def token(key: Any = KEY, algorithm: str = "ES256", **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": str(USER),
        "aud": "authenticated",
        "iss": ISSUER,
        "role": "authenticated",
        "is_anonymous": False,
        "iat": now,
        "exp": now + 600,
        **overrides,
    }
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, key, algorithm=algorithm)


def b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def unsigned() -> str:
    """`alg: none` with otherwise valid claims."""
    claims = jwt.decode(token(), options={"verify_signature": False})
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(claims)}."


@pytest.fixture
def client() -> TestClient:
    app = create_app(Settings(environment="test"))
    app.state.verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())

    @app.get(f"{API_PREFIX}/_test/whoami")
    def whoami(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
        return {"id": str(user.id)}

    return TestClient(app, raise_server_exceptions=False)


def whoami(client: TestClient, **headers: str) -> Any:
    return client.get(f"{API_PREFIX}/_test/whoami", headers=headers)


def test_valid_token_identifies_the_user(client: TestClient) -> None:
    response = whoami(client, Authorization=f"Bearer {token()}")
    assert response.status_code == 200
    assert response.json() == {"id": str(USER)}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Bearer"},
        {"Authorization": f"Basic {token()}"},
        # The API never reads cookies, so a cross-site request carrying one gets nothing (no CSRF surface).
        {"Cookie": f"sb-access-token={token()}"},
    ],
)
def test_requests_without_a_bearer_token_are_unauthenticated(client: TestClient, headers: dict[str, str]) -> None:
    response = whoami(client, **headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda: token(exp=int(time.time()) - 5), id="expired"),
        pytest.param(lambda: token(key=OTHER_KEY), id="forged-signature"),
        pytest.param(lambda: token(aud="other"), id="wrong-audience"),
        pytest.param(lambda: token(iss="http://evil.test/auth/v1"), id="wrong-issuer"),
        pytest.param(lambda: token(sub=None), id="no-subject"),
        pytest.param(lambda: token(sub="not-a-uuid"), id="bad-subject"),
        pytest.param(lambda: token(exp=None), id="no-expiry"),
        pytest.param(lambda: token(role="service_role"), id="service-role"),
        pytest.param(lambda: token(role="anon"), id="anon-key"),
        pytest.param(lambda: token(key="a-shared-secret-long-enough-for-hs256", algorithm="HS256"), id="symmetric"),
        pytest.param(unsigned, id="unsigned"),
        pytest.param(lambda: "not.a.jwt", id="garbage"),
    ],
)
def test_invalid_tokens_are_rejected(client: TestClient, bad: Any) -> None:
    response = whoami(client, Authorization=f"Bearer {bad()}")
    assert response.status_code == 401
    body = response.text
    assert response.json()["error"]["code"] == "unauthenticated"
    assert "eyJ" not in body  # never echo the token


def test_anonymous_sessions_cannot_act_as_accounts(client: TestClient) -> None:
    # ADR-0017: anonymous sign-in stays off, but claims are still checked in case it is ever enabled.
    response = whoami(client, Authorization=f"Bearer {token(is_anonymous=True)}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_metadata_claims_do_not_change_identity(client: TestClient) -> None:
    sneaky = token(user_metadata={"sub": str(uuid.uuid4()), "is_admin": True}, app_metadata={"role": "admin"})
    assert whoami(client, Authorization=f"Bearer {sneaky}").json() == {"id": str(USER)}


def test_unconfigured_auth_is_unavailable_not_open() -> None:
    app = create_app(Settings(environment="test"))

    @app.get(f"{API_PREFIX}/_test/whoami")
    def guarded(user: Annotated[User, Depends(current_user)]) -> None: ...

    response = TestClient(app).get(f"{API_PREFIX}/_test/whoami", headers={"Authorization": f"Bearer {token()}"})
    assert response.status_code == 503


def test_unreachable_key_set_is_an_outage(client: TestClient) -> None:
    def down(_token: str) -> Any:
        raise jwt.PyJWKClientConnectionError("connection refused")

    app = client.app
    assert isinstance(app, FastAPI)
    app.state.verifier = TokenVerifier(ISSUER, down)
    response = whoami(client, Authorization=f"Bearer {token()}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"


def test_settings_build_the_jwks_verifier_from_the_supabase_url() -> None:
    app = create_app(Settings(environment="test", supabase_url="http://127.0.0.1:54321/"))
    verifier = app.state.verifier
    assert isinstance(verifier, TokenVerifier)
    assert verifier.issuer == "http://127.0.0.1:54321/auth/v1"


def test_cors_allows_only_configured_origins_without_credentials() -> None:
    app = create_app(Settings(environment="test", cors_origins=["https://guthub.test"]))
    client = TestClient(app)
    preflight = {"Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "authorization,content-type"}
    allowed = client.options(f"{API_PREFIX}/me", headers={"Origin": "https://guthub.test", **preflight})
    assert allowed.status_code == 200
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://guthub.test"
    assert "Access-Control-Allow-Credentials" not in allowed.headers
    simple = client.get(f"{API_PREFIX}/health", headers={"Origin": "https://guthub.test"})
    assert "retry-after" in simple.headers["Access-Control-Expose-Headers"].lower()  # rate-limit hint readable
    denied = client.options(f"{API_PREFIX}/me", headers={"Origin": "https://evil.test", **preflight})
    assert "Access-Control-Allow-Origin" not in denied.headers


@pytest.mark.parametrize(
    ("amr", "mailed"),
    [
        ([{"method": "otp", "timestamp": 1}], "dr@cgmh.org.tw"),
        ([{"method": "magiclink", "timestamp": 1}], "dr@cgmh.org.tw"),
        ([{"method": "password", "timestamp": 1}], None),  # sign-up confirmations are off: no mailbox was proven
        (None, None),
        ("otp", None),
    ],
)
def test_the_email_counts_only_for_sessions_opened_from_a_mailed_link(amr: Any, mailed: str | None) -> None:
    verifier = TokenVerifier(ISSUER, lambda _token: KEY.public_key())
    claims = {"email": "dr@cgmh.org.tw"} | ({"amr": amr} if amr is not None else {})
    assert verifier.verify(token(**claims)).mailed_email == mailed
