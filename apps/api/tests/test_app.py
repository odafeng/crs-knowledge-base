"""Unit and contract tests for the API foundation (B2 #59)."""

from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "contracts/openapi.yaml").read_text())


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


def client_with_test_routes() -> TestClient:
    app = create_app(Settings(environment="test"))

    @app.get(f"{API_PREFIX}/_test/forbidden")
    def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Not your comment")

    @app.get(f"{API_PREFIX}/_test/limited")
    def limited() -> None:
        raise HTTPException(status_code=429)

    @app.get(f"{API_PREFIX}/_test/crash")
    def crash() -> None:
        raise RuntimeError("postgres://user:secret@db/leak")

    @app.get(f"{API_PREFIX}/_test/items/{{item_id}}")
    def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    return TestClient(app, raise_server_exceptions=False)


# --- settings ---------------------------------------------------------------


def test_settings_read_environment_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_ENVIRONMENT", "staging")
    monkeypatch.setenv("GUTHUB_DATABASE_URL", "postgresql://api@db/guthub")
    settings = Settings()
    assert settings.environment == "staging"
    assert settings.database_url is not None
    assert "postgresql" not in repr(settings)  # secret stays out of logs


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_environments_require_a_database(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.delenv("GUTHUB_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="GUTHUB_DATABASE_URL"):
        Settings(environment=environment)  # pyright: ignore[reportArgumentType]


def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="prod")  # pyright: ignore[reportArgumentType]


def test_app_exposes_injected_settings() -> None:
    settings = Settings(environment="test")
    assert create_app(settings).state.settings is settings


# --- health -----------------------------------------------------------------


def test_health_matches_contract_and_is_not_cached() -> None:
    response = TestClient(create_app(Settings(environment="test"))).get(f"{API_PREFIX}/health")
    assert response.status_code == 200
    schema("Health").validate(response.json())
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


# --- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/_test/forbidden", 403, "forbidden"),
        ("/_test/limited", 429, "rate_limited"),
        ("/_test/items/not-a-number", 422, "validation_error"),
        ("/does-not-exist", 404, "not_found"),
        ("/_test/crash", 500, "unavailable"),
    ],
)
def test_errors_use_contract_shape(path: str, status: int, code: str) -> None:
    response = client_with_test_routes().get(f"{API_PREFIX}{path}")
    assert response.status_code == status
    body = response.json()
    schema("Error").validate(body)
    assert body["error"]["code"] == code
    assert body["error"]["requestId"] == response.headers["x-request-id"]
    assert response.headers["cache-control"] == "no-store"


def test_http_exception_detail_is_kept_as_message() -> None:
    body = client_with_test_routes().get(f"{API_PREFIX}/_test/forbidden").json()
    assert body["error"]["message"] == "Not your comment"


def test_unhandled_error_does_not_leak_internals() -> None:
    response = client_with_test_routes().get(f"{API_PREFIX}/_test/crash")
    assert "secret" not in response.text
    assert "postgres" not in response.text


def test_request_ids_are_unique_and_ignore_client_value() -> None:
    client = TestClient(create_app(Settings(environment="test")))
    first = client.get(f"{API_PREFIX}/health", headers={"X-Request-ID": "attacker\nvalue"})
    second = client.get(f"{API_PREFIX}/health")
    assert first.headers["x-request-id"] != "attacker\nvalue"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


# --- contract ---------------------------------------------------------------


def test_every_route_is_declared_in_the_contract() -> None:
    server = SPEC["servers"][0]["url"]
    assert server == API_PREFIX
    declared = {(f"{server}{path}", method.upper()) for path, ops in SPEC["paths"].items() for method in ops}
    app = create_app(Settings(environment="test"))
    served = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods or ()
        if method != "HEAD"
    }
    assert served
    assert served <= declared, served - declared


def test_framework_docs_are_disabled_so_the_contract_is_the_only_spec() -> None:
    client = TestClient(create_app(Settings(environment="test")))
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404


# --- writes paused (F3 #78) ---------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/papers/niche2/comments"),
        ("PUT", "/me"),
        ("PATCH", "/comments/00000000-0000-4000-8000-000000000001"),
        ("DELETE", "/comments/00000000-0000-4000-8000-000000000001/likes"),
        ("POST", "/admin/comments/00000000-0000-4000-8000-000000000001/author"),
    ],
)
def test_paused_writes_answer_maintenance_before_anything_else(method: str, path: str) -> None:
    client = TestClient(
        create_app(Settings(environment="test", writes_paused=True, cors_origins=["https://guthub.tw"]))
    )
    response = client.request(method, f"{API_PREFIX}{path}", headers={"Origin": "https://guthub.tw"})
    assert response.status_code == 503
    body = response.json()
    schema("Error").validate(body)
    assert body["error"]["code"] == "unavailable"
    # Retry-After marks planned maintenance; a database outage answers 503 without it.
    assert response.headers["retry-after"] == "600"
    assert body["error"]["requestId"] == response.headers["x-request-id"]
    assert response.headers["access-control-allow-origin"] == "https://guthub.tw"


def test_paused_writes_leave_reads_and_preflight_alone() -> None:
    client = TestClient(
        create_app(Settings(environment="test", writes_paused=True, cors_origins=["https://guthub.tw"]))
    )
    assert client.get(f"{API_PREFIX}/health").status_code == 200
    preflight = client.options(
        f"{API_PREFIX}/me",
        headers={"Origin": "https://guthub.tw", "Access-Control-Request-Method": "PUT"},
    )
    assert preflight.status_code == 200


def test_open_writes_have_no_maintenance_answer() -> None:
    # Without a Supabase URL a signed-in endpoint is unavailable, but that outage carries no Retry-After.
    response = TestClient(create_app(Settings(environment="test"))).put(f"{API_PREFIX}/me")
    assert "retry-after" not in response.headers
