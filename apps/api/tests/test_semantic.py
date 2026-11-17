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
from guthub_api.semantic import DAYS, INDEXER_RESERVE, PerMinute, _month, _today
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
        conn.execute("delete from app.query_usage where day = %s", (_today(),))
        # Cards are always public; the paper "test-gone" is in no public view, as after a withdrawal.
        chunks = [("card", "test-a", "EC + cetuximab"), ("card", "test-b", "NICHE-2"), ("paper", "test-gone", "Gone")]
        for i, (kind, ref, title) in enumerate(chunks):
            conn.execute(
                "insert into app.search_chunks (kind, ref, path, title, snippet, content_hash, model, embedding)"
                " values (%s, %s, %s, %s, 'snippet', 'h', 'voyage-4', %s::extensions.vector)",
                (kind, ref, f"/x/{ref}/", title, literal(unit(i))),
            )
        yield conn
        conn.execute("delete from app.search_chunks where ref like 'test-%'")
        conn.execute("delete from app.embedding_usage where month = %s", (_month(),))
        conn.execute("delete from app.query_usage where day = %s", (_today(),))


@pytest.fixture
def client(sql: Any) -> Iterator[TestClient]:
    app = create_app(Settings(environment="test", database_url=API_DB_URL, surgeon_roster_url=None))  # pyright: ignore[reportArgumentType]
    queries: list[str] = []

    def embed(text: str) -> tuple[list[float], int]:
        queries.append(text)
        if text == "broken":
            raise ValueError("unexpected response")
        return {"braf": unit(0), "both": unit(0, 1), "weather": unit(5), "gone": unit(2)}[text], 7

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


def test_withdrawn_content_is_never_a_result(client: TestClient) -> None:
    hits = client.post(URL, json={"query": "gone"}).json()["results"]
    assert [r for r in hits if r["path"].startswith("/x/")] == []


def test_query_tokens_are_counted_for_the_month(client: TestClient, sql: Any) -> None:
    client.post(URL, json={"query": "braf"})
    client.post(URL, json={"query": "  braf  "})  # stripped before embedding
    assert sql.execute("select tokens from app.embedding_usage where month = %s", (_month(),)).fetchone() == (14,)
    assert cast("FastAPI", client.app).state.queries == ["braf", "braf"]


def test_a_spent_budget_pauses_search_but_leaves_room_for_the_indexer(client: TestClient, sql: Any) -> None:
    # Queries stop INDEXER_RESERVE short of the cap: the indexer keeps the last million tokens.
    sql.execute(
        "insert into app.embedding_usage (month, tokens) values (%s, %s)",
        (date.fromisoformat(_month()), 80_000_000 - INDEXER_RESERVE),
    )
    assert client.post(URL, json={"query": "braf"}).status_code == 503
    assert cast("FastAPI", client.app).state.queries == []


def test_unconfigured_search_is_unavailable(client: TestClient) -> None:
    cast("FastAPI", client.app).state.embed = None
    assert client.post(URL, json={"query": "braf"}).status_code == 503


@pytest.mark.parametrize("body", [{"query": "x"}, {"query": "y" * 201}, {"query": "a\x00b"}, {"q": "braf"}, {}])
def test_malformed_queries_are_refused(client: TestClient, body: dict[str, str]) -> None:
    assert client.post(URL, json=body).status_code == 422


def test_a_failed_call_releases_its_reservation(client: TestClient, sql: Any) -> None:
    assert client.post(URL, json={"query": "broken"}).status_code == 503
    assert sql.execute("select tokens from app.embedding_usage where month = %s", (_month(),)).fetchone() == (0,)


def test_one_address_is_limited_per_minute(client: TestClient) -> None:
    app = cast("FastAPI", client.app)
    app.state.search_limiter = PerMinute(2)
    first = {"X-Forwarded-For": "203.0.113.9, 198.51.100.1"}
    assert [client.post(URL, json={"query": "braf"}, headers=first).status_code for _ in range(3)] == [200, 200, 429]
    # Only the address Cloud Run appended counts; a forged first entry changes nothing.
    forged = {"X-Forwarded-For": "192.0.2.77, 198.51.100.1"}
    assert client.post(URL, json={"query": "braf"}, headers=forged).status_code == 429
    assert client.post(URL, json={"query": "braf"}, headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 200


def test_a_day_may_spend_only_its_share_of_the_month(client: TestClient, sql: Any) -> None:
    share = (80_000_000 - INDEXER_RESERVE) // DAYS
    sql.execute("insert into app.query_usage (day, tokens) values (%s, %s)", (date.fromisoformat(_today()), share))
    assert client.post(URL, json={"query": "braf"}).status_code == 503
    # The month's reservation is handed back when the day refuses.
    assert sql.execute("select tokens from app.embedding_usage where month = %s", (_month(),)).fetchone() == (0,)


def test_ipv6_clients_count_per_slash_64(client: TestClient) -> None:
    app = cast("FastAPI", client.app)
    app.state.search_limiter = PerMinute(1)
    one = {"X-Forwarded-For": "2001:db8:1:2::1"}
    same_prefix = {"X-Forwarded-For": "2001:db8:1:2:ffff::9"}
    assert client.post(URL, json={"query": "braf"}, headers=one).status_code == 200
    assert client.post(URL, json={"query": "braf"}, headers=same_prefix).status_code == 429
    assert client.post(URL, json={"query": "braf"}, headers={"X-Forwarded-For": "2001:db8:1:3::1"}).status_code == 200


def test_the_limiter_forgets_the_least_recent_clients() -> None:
    limiter = PerMinute(1, max_clients=2)
    assert limiter.allow("a") and limiter.allow("b") and limiter.allow("c")
    assert limiter.allow("a")  # "a" was dropped to make room, so it starts afresh
    assert not limiter.allow("c")
