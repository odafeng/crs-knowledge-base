"""Read API against the real knowledge base (B5 #62).

A session fixture imports data/*.json with the B4 importer (committing to the test database), then the app connects
as the guthub_api role only. Responses are validated against contracts/openapi.yaml. Needs GUTHUB_TEST_DATABASE_URL;
skips without it unless GUTHUB_REQUIRE_DB=1.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from guthub_api.content import TOPIC_ORDER, clean
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
SPEC = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text())
RAW = json.loads((ROOT / "data/papers.json").read_text(encoding="utf-8"))
NEWS = json.loads((ROOT / "data/news.json").read_text(encoding="utf-8"))
RAW_PAPERS = {p["id"]: p for block in RAW.values() for p in block.get("papers", [])}

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")
if not DB_URL:
    if os.environ.get("GUTHUB_REQUIRE_DB") == "1":
        raise RuntimeError("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    pytest.skip("GUTHUB_TEST_DATABASE_URL not set", allow_module_level=True)

# Same database, but the session runs as guthub_api: the API must work with exactly the grants B3 gives it.
API_URL = f"{DB_URL}{'&' if '?' in DB_URL else '?'}options={quote('-c role=guthub_api')}"


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


def text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    assert DB_URL
    subprocess.run(
        [sys.executable, "import_content.py", "--database-url", DB_URL], cwd=ROOT, check=True, capture_output=True
    )
    app = create_app(Settings(environment="test", database_url=API_URL))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        yield test_client


def get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(f"{API_PREFIX}{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def all_pages(client: TestClient, path: str, **params: Any) -> list[dict[str, Any]]:
    items, cursor = [], None
    while True:
        page = get(client, path, **params, **({"cursor": cursor} if cursor else {}))
        items += page["items"]
        cursor = page["nextCursor"]
        if cursor is None:
            return items


# --- health --------------------------------------------------------------------------------------------------------


def test_health_checks_the_database(client: TestClient) -> None:
    assert get(client, "/health") == {"status": "ok"}


# --- papers --------------------------------------------------------------------------------------------------------


def test_every_paper_matches_the_contract_and_the_source(client: TestClient) -> None:
    papers = all_pages(client, "/papers", limit=7)
    assert len(papers) == len(RAW_PAPERS)
    assert len({p["id"] for p in papers}) == len(papers)  # pages neither overlap nor skip
    validator = schema("Paper")
    for paper in papers:
        validator.validate(paper)
        raw = RAW_PAPERS[paper["id"]]
        for key in ("year", "journal", "studyType", "regimen", "endpoint", "result", "bottomLine", "source"):
            assert paper[key] == raw[key], (paper["id"], key)
        assert paper["n"] == raw.get("n")
        assert sorted(map(json.dumps, paper["relations"])) == sorted(map(json.dumps, raw.get("relations", [])))
        assert len(paper["commentary"]) == len(raw.get("commentary", []))


def test_paper_detail_keeps_the_evidence_text(client: TestClient) -> None:
    with_detail = [pid for pid, raw in RAW_PAPERS.items() if raw.get("file")]
    for paper_id in with_detail:
        paper = get(client, f"/papers/{paper_id}")
        assert paper["detailHtml"]
        assert "style=" not in paper["detailHtml"]
        assert "target=" not in paper["detailHtml"]
    # Sanitizing removes markup only: the visible text of every document survives.
    assert DB_URL
    with psycopg.connect(DB_URL) as conn:
        for (html,) in conn.execute("select detail_html from app.papers where detail_html <> ''"):
            assert text(clean(html)) == text(html)


def test_topic_filter_and_ordering(client: TestClient) -> None:
    papers = all_pages(client, "/papers", topic="mCRC-MSI-H", limit=100)
    expected = {pid for pid, raw in RAW_PAPERS.items() if pid in {p["id"] for p in RAW["mCRC-MSI-H"]["papers"]}}
    assert {p["id"] for p in papers} == expected
    assert [p["year"] for p in papers] == sorted((p["year"] for p in papers), reverse=True)


# --- news ----------------------------------------------------------------------------------------------------------


def test_news_matches_contract_and_source(client: TestClient) -> None:
    stories = all_pages(client, "/news", limit=3)
    assert len(stories) == len(NEWS)
    raw = {n["id"]: n for n in NEWS}
    for story in stories:
        schema("News").validate(story)
        assert story["headline"] == raw[story["id"]]["headline"]
        assert story["review"]["status"] == raw[story["id"]]["review"]["status"]  # AI-unreviewed flag survives
    assert get(client, f"/news/{NEWS[0]['id']}")["id"] == NEWS[0]["id"]


# --- topics --------------------------------------------------------------------------------------------------------


def test_topics_follow_contract_order_with_counts(client: TestClient) -> None:
    topics = all_pages(client, "/topics")
    assert tuple(t["key"] for t in topics) == TOPIC_ORDER
    assert tuple(SPEC["components"]["schemas"]["TopicKey"]["enum"]) == TOPIC_ORDER
    for topic in topics:
        schema("Topic").validate(topic)
        assert topic["paperCount"] == len(RAW[topic["key"]].get("papers", []))


def test_topic_detail_sanitizes_card_html(client: TestClient) -> None:
    topic = get(client, "/topics/mCRC-BRAF-V600E")
    raw_cards = RAW["mCRC-BRAF-V600E"]["standard_of_care"]["cards"]
    assert [c["title"] for c in topic["standardOfCare"]] == [c["title"] for c in raw_cards]
    assert topic["standardOfCare"][0]["regulatory"] == raw_cards[0]["regulatory"]
    robotic = get(client, "/topics/robotic-surgery")["roboticSections"]
    for section in robotic:
        for item in section["timeline"]:
            assert "<script" not in item["finding"]
        assert all("target=" not in card["body"] for card in section["cards"])


def test_empty_topic_has_zero_papers(client: TestClient) -> None:
    assert get(client, "/topics/robotic-surgery")["paperCount"] == 0
    assert get(client, "/papers", topic="robotic-surgery") == {"items": [], "nextCursor": None}


# --- search --------------------------------------------------------------------------------------------------------


def test_search_finds_papers_and_news_with_site_paths(client: TestClient) -> None:
    paper = next(iter(RAW_PAPERS.values()))
    hits = all_pages(client, "/search", q=paper["id"])
    for hit in hits:
        schema("SearchHit").validate(hit)
    match = next(h for h in hits if h["kind"] == "paper" and h["id"] == paper["id"])
    assert match["path"] == f"/papers/{paper['id'].lower().replace('_', '-')}/"
    assert match["title"] == f"{unescape(paper['regimen'])}（{unescape(paper['journal'])} {paper['year']}）"

    story = NEWS[0]
    word = story["dek"][:4]
    news_hits = [h for h in all_pages(client, "/search", q=word) if h["kind"] == "news"]
    assert {"kind": "news", "id": story["id"], "path": f"/news/{story['id']}/"}.items() <= next(
        h for h in news_hits if h["id"] == story["id"]
    ).items()


def test_search_treats_wildcards_literally(client: TestClient) -> None:
    assert get(client, "/search", q="%%")["items"] == []
    assert get(client, "/search", q="__")["items"] == []


# --- withdrawn content ---------------------------------------------------------------------------------------------


def test_withdrawn_paper_disappears_everywhere(client: TestClient) -> None:
    target = next(
        pid
        for pid, raw in RAW_PAPERS.items()
        if any(r["targetId"] == pid for other in RAW_PAPERS.values() for r in other.get("relations", []))
    )
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("update app.papers set withdrawn_at = now() where id = %s", (target,))
        try:
            assert client.get(f"{API_PREFIX}/papers/{target}").status_code == 404
            papers = all_pages(client, "/papers", limit=100)
            assert target not in {p["id"] for p in papers}
            assert all(r["targetId"] != target for p in papers for r in p["relations"])
            assert all(h["id"] != target for h in all_pages(client, "/search", q=target))
        finally:
            conn.execute("update app.papers set withdrawn_at = null where id = %s", (target,))


# --- errors --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/papers/does-not-exist", 404, "not_found"),
        ("/news/does-not-exist", 404, "not_found"),
        ("/topics/not-a-topic", 422, "validation_error"),
        ("/papers?topic=not-a-topic", 422, "validation_error"),
        ("/papers?limit=0", 422, "validation_error"),
        ("/papers?limit=101", 422, "validation_error"),
        ("/papers?cursor=not-base64!", 422, "validation_error"),
        ("/papers?cursor=eyJvIjogLTF9", 422, "validation_error"),  # {"o": -1}
        ("/search?q=a", 422, "validation_error"),
        ("/search?q=%20%20a%20", 422, "validation_error"),
    ],
)
def test_bad_requests_use_the_error_contract(client: TestClient, path: str, status: int, code: str) -> None:
    response = client.get(f"{API_PREFIX}{path}")
    assert response.status_code == status, response.text
    schema("Error").validate(response.json())
    assert response.json()["error"]["code"] == code


def test_database_outage_returns_503_without_details() -> None:
    app = create_app(Settings(environment="test", database_url="postgresql://guthub_api@127.0.0.1:1/none"))  # pyright: ignore[reportArgumentType]
    with TestClient(app) as test_client:
        for path in ("/health", "/papers"):
            response = test_client.get(f"{API_PREFIX}{path}")
            assert response.status_code == 503
            schema("Error").validate(response.json())
            assert response.json()["error"]["code"] == "unavailable"
            assert "127.0.0.1" not in response.text


# --- daily pick (G2 #113) ---------------------------------------------------------------------------------------------


def test_daily_pick_takes_the_days_story_with_its_papers_bottom_line(client: TestClient) -> None:
    from guthub_api.daily import collect

    assert DB_URL
    with psycopg.connect(DB_URL) as conn:
        news = conn.execute(
            "select id, paper_id, published_at from app.public_news order by published_at desc limit 1"
        ).fetchone()
        assert news is not None
        news_id, paper_id, day = news
        bottom_line = conn.execute("select bottom_line from app.papers where id = %s", (paper_id,)).fetchone()
        assert bottom_line is not None
        kinds = {c.kind for c in collect(conn, day)}
    assert "news" in kinds

    response = client.get(f"{API_PREFIX}/daily-pick", params={"date": day.isoformat()})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    schema("DailyPick").validate(body)
    pick = body["pick"]
    assert pick["kind"] == "news" and pick["date"] == day.isoformat()
    assert pick["url"].startswith("/news/") and pick["conclusion"] == bottom_line[0]


def test_daily_pick_is_empty_on_a_day_without_new_content(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/daily-pick", params={"date": "2001-01-01"})
    assert response.status_code == 200
    assert response.json() == {"date": "2001-01-01", "pick": None}
    assert client.get(f"{API_PREFIX}/daily-pick", params={"date": "yesterday"}).status_code == 422
