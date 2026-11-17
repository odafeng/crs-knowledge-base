"""Natural-language search (H3 #125): ranking, the relevance threshold, the monthly budget and refusals.

Runs against the real database like test_accounts.py, with a fake embedder: unit vectors stand in for meanings.
"""

from collections.abc import Iterator
from datetime import date
from typing import TYPE_CHECKING, Any, cast

import psycopg
import pytest
from fastapi.testclient import TestClient

from guthub_api.main import API_PREFIX, create_app
from guthub_api.semantic import _month
from guthub_api.settings import Settings
from test_accounts import API_DB_URL, DB_URL, schema

if TYPE_CHECKING:
    from fastapi import FastAPI

URL = f"{API_PREFIX}/semantic-search"


def unit(i: int, j: int | None = None) -> list[float]:
    """e_i, or the normalized e_i + e_j (cosine 0.707 to both)."""
    v = [0.0] * 1024
    v[i] = 1.0
    if j is not None:
        v[i] = v[j] = 0.5**0.5
    return v


def literal(v: list[float]) -> str:
    return "[" + ",".join(map(str, v)) + "]"


@pytest.fixture
def sql() -> Iterator[Any]:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("delete from app.search_chunks where ref like 'test-%'")
        conn.execute("delete from app.embedding_usage where month = %s", (_month(),))
        for i, (kind, ref, title) in enumerate([("paper", "test-a", "EC + cetuximab"), ("news", "test-b", "NICHE-2")]):
            conn.execute(
                "insert into app.search_chunks (kind, ref, path, title, snippet, content_hash, model, embedding)"
                " values (%s, %s, %s, %s, 'snippet', 'h', 'voyage-4', %s::extensions.vector)",
                (kind, ref, f"/x/{ref}/", title, literal(unit(i))),
            )
        yield conn
        conn.execute("delete from app.search_chunks where ref like 'test-%'")
        conn.execute("delete from app.embedding_usage where month = %s", (_month(),))


@pytest.fixture
def client(sql: Any) -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL, surgeon_roster_url=None))  # pyright: ignore[reportArgumentType]
    queries: list[str] = []

    def embed(text: str) -> tuple[list[float], int]:
        queries.append(text)
        return {"braf": unit(0), "both": unit(0, 1), "weather": unit(5)}[text], 7

    app.state.embed = embed
    app.state.queries = queries
    with TestClient(app) as test_client:
        yield test_client


def test_results_are_ranked_and_the_unrelated_are_dropped(client: TestClient, sql: Any) -> None:
    response = client.post(URL, json={"query": "both"})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    schema("SemanticResults").validate(response.json())
    mine = [r for r in response.json()["results"] if r["path"].startswith("/x/")]
    assert sorted((r["title"], r["score"]) for r in mine) == [("EC + cetuximab", 0.707), ("NICHE-2", 0.707)]
    only = [r for r in client.post(URL, json={"query": "braf"}).json()["results"] if r["path"].startswith("/x/")]
    assert [r["title"] for r in only] == ["EC + cetuximab"]  # NICHE-2 scores 0, below the threshold
    assert [
        r for r in client.post(URL, json={"query": "weather"}).json()["results"] if r["path"].startswith("/x/")
    ] == []


def test_query_tokens_are_counted_for_the_month(client: TestClient, sql: Any) -> None:
    client.post(URL, json={"query": "braf"})
    client.post(URL, json={"query": "  braf  "})  # stripped before embedding
    assert sql.execute("select tokens from app.embedding_usage where month = %s", (_month(),)).fetchone() == (14,)
    assert cast("FastAPI", client.app).state.queries == ["braf", "braf"]


def test_a_spent_budget_pauses_search(client: TestClient, sql: Any) -> None:
    sql.execute(
        "insert into app.embedding_usage (month, tokens) values (%s, %s)", (date.fromisoformat(_month()), 80_000_000)
    )
    assert client.post(URL, json={"query": "braf"}).status_code == 503
    assert cast("FastAPI", client.app).state.queries == []


def test_unconfigured_search_is_unavailable(client: TestClient) -> None:
    cast("FastAPI", client.app).state.embed = None
    assert client.post(URL, json={"query": "braf"}).status_code == 503


@pytest.mark.parametrize("body", [{"query": "x"}, {"query": "y" * 201}, {"query": "a\x00b"}, {"q": "braf"}, {}])
def test_malformed_queries_are_refused(client: TestClient, body: dict[str, str]) -> None:
    assert client.post(URL, json=body).status_code == 422
