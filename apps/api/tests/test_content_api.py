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
from datetime import timedelta
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb

from guthub_api.content import TOPIC_ORDER, clean
from guthub_api.main import API_PREFIX, create_app
from guthub_api.settings import Settings
from guthub_api.taxonomy import DOMAIN_ORDER

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
    # Write layer sanitizes HTML once on ingest (K6 #256): stored DB HTML already matches the allowlist.
    assert DB_URL
    with psycopg.connect(DB_URL) as conn:
        for (html,) in conn.execute("select detail_html from app.papers where detail_html <> ''"):
            assert html == clean(html)
            assert text(clean(html)) == text(html)


def test_topic_filter_and_ordering(client: TestClient) -> None:
    papers = all_pages(client, "/papers", topic="mCRC-MSI-H", limit=100)
    expected = {pid for pid, raw in RAW_PAPERS.items() if pid in {p["id"] for p in RAW["mCRC-MSI-H"]["papers"]}}
    assert {p["id"] for p in papers} == expected
    assert [p["year"] for p in papers] == sorted((p["year"] for p in papers), reverse=True)


def test_slim_paper_list_omits_detail_html_and_by_slug_returns_full_paper(client: TestClient) -> None:
    slim = all_pages(client, "/papers", includeDetail="false", limit=100)
    assert len(slim) == len(RAW_PAPERS)
    validator = schema("Paper")
    for paper in slim:
        validator.validate(paper)
        assert paper["detailHtml"] == ""

    with_detail = next(pid for pid, raw in RAW_PAPERS.items() if raw.get("file"))
    slug = with_detail.lower().replace("_", "-")
    full = get(client, f"/papers/by-slug/{slug}")
    validator.validate(full)
    assert full["id"] == with_detail
    assert full["detailHtml"]
    assert client.get(f"{API_PREFIX}/papers/by-slug/no-such-slug").status_code == 404
    assert client.get(f"{API_PREFIX}/papers/by-slug/INVALID_SLUG").status_code == 422


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


# --- news events (N6 #291, ADR-0031) -------------------------------------------------------------------------------


def test_news_events_expose_only_published_items_and_filter_by_domain_and_search(client: TestClient) -> None:
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        pub_id = "n6-test-pub-event"
        draft_id = "n6-test-draft-event"
        withdrawn_id = "n6-test-withdrawn-event"
        src_id = "n6-test-src"
        try:
            conn.execute(
                "insert into app.news_source_registry"
                " (id, name, source_type, base_url, terms_reviewed_at, trust_tier, enabled, last_error_at, last_error)"
                " values (%s, 'Test Delayed Source', 'regulatory', 'https://example.org', '2026-11-01', 'tier1', true, now(), 'timeout')"
                " on conflict (id) do update set enabled = true, last_error_at = now(), last_success_at = null",
                (src_id,),
            )
            for eid, status, is_withdrawn, headline in (
                (pub_id, "published", False, "TFDA 核准大腸直腸癌新標靶適應症"),
                (draft_id, "draft", False, "未發布草稿秘密事件"),
                (withdrawn_id, "withdrawn", True, "已撤回事件"),
            ):
                conn.execute(
                    "insert into app.news_events"
                    " (id, dedup_key, category, geography, evidence_status, risk_tier, status, review_status,"
                    "  event_date, published_at, effective_date, withdrawn_at)"
                    " values (%s, %s, 'regulatory', 'taiwan', 'approved', 'low', %s, 'reviewed',"
                    "  '2026-11-26', '2026-11-27', '2026-12-01', case when %s then now() else null end)",
                    (eid, f"dedup-{eid}", status, is_withdrawn),
                )
                rev_id = conn.execute(
                    "insert into app.news_revisions"
                    " (event_id, revision_number, headline, what_happened, why_it_matters,"
                    "  clinical_relevance, evidence_limitations, created_by)"
                    " values (%s, 1, %s, 'TFDA 正式公告新適應症', '擴大一線治療選擇',"
                    "  '適用轉移性大腸直腸癌病患', '需確認生物標記檢測', 'test') returning id",
                    (eid, headline),
                ).fetchone()
                assert rev_id is not None
                conn.execute("update app.news_events set current_revision_id = %s where id = %s", (rev_id[0], eid))
                conn.execute(
                    "insert into app.news_event_domains (event_id, domain_slug, is_primary, taxonomy_version)"
                    " values (%s, 'colorectal-oncology', true, '1.0'), (%s, 'endoscopy', false, '1.0')",
                    (eid, eid),
                )
                conn.execute(
                    "insert into app.news_event_sources (event_id, url, title, publisher, source_kind, published_at)"
                    " values (%s, %s, 'TFDA 公告', 'TFDA', 'regulatory', '2026-11-26')",
                    (eid, f"https://www.fda.gov.tw/{eid}"),
                )

            page = get(client, "/news-events", domain="colorectal-oncology")
            schema("NewsEventPage").validate(page)
            returned_ids = {item["id"] for item in page["items"]}
            assert pub_id in returned_ids
            assert draft_id not in returned_ids
            assert withdrawn_id not in returned_ids
            assert any(s["id"] == src_id and s["degraded"] is True for s in page["degradedSources"])

            # Secondary domain filter also finds the published event.
            sec_page = get(client, "/news-events", domain="endoscopy", category="regulatory", geography="taiwan")
            assert any(item["id"] == pub_id for item in sec_page["items"])

            detail = get(client, f"/news-events/{pub_id}")
            schema("NewsEvent").validate(detail)
            assert detail["primaryDomain"] == "colorectal-oncology"
            assert detail["secondaryDomains"] == ["endoscopy"]
            assert detail["effectiveDate"] == "2026-12-01"

            # Draft and withdrawn events must return 404.
            assert client.get(f"{API_PREFIX}/news-events/{draft_id}").status_code == 404
            assert client.get(f"{API_PREFIX}/news-events/{withdrawn_id}").status_code == 404

            # Search finds published event (including by secondary domain) and never leaks draft/withdrawn.
            search_hits = all_pages(client, "/search", q="TFDA 核准大腸直腸癌")
            assert any(
                h["kind"] == "news_event" and h["id"] == pub_id and h["path"] == f"/news/events/{pub_id}/"
                for h in search_hits
            )
            assert all(h["id"] != draft_id for h in all_pages(client, "/search", q="未發布草稿秘密事件"))
            assert all(h["id"] != withdrawn_id for h in all_pages(client, "/search", q="已撤回事件"))
        finally:
            conn.execute("delete from app.news_events where id = any(%s)", ([pub_id, draft_id, withdrawn_id],))
            conn.execute("delete from app.news_source_registry where id = %s", (src_id,))


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


# --- domains (T1 #282, ADR-0030) -----------------------------------------------------------------------------------


def test_domains_follow_registry_order_and_filter_multi_domain_papers(client: TestClient) -> None:
    domains = all_pages(client, "/domains")
    assert tuple(d["slug"] for d in domains) == DOMAIN_ORDER
    assert tuple(SPEC["components"]["schemas"]["DomainSlug"]["enum"]) == DOMAIN_ORDER
    for domain in domains:
        schema("Domain").validate(domain)

    oncology = get(client, "/domains/colorectal-oncology")
    schema("Domain").validate(oncology)
    assert any(s["legacyTopicKey"] == "mCRC-BRAF-V600E" for s in oncology["subtopics"])

    target = next(iter(RAW_PAPERS))
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute(
            "insert into app.paper_domains"
            " (paper_id, domain_slug, is_primary, subtopic_id, taxonomy_version, assigned_by) values"
            " (%s, 'colorectal-oncology', true, 'mcrc-braf-v600e', '1.0', 'test'),"
            " (%s, 'surgical-intelligence', false, 'surgical-risk-prediction', '1.0', 'test')"
            " on conflict do nothing",
            (target, target),
        )
        try:
            paper = get(client, f"/papers/{target}")
            schema("Paper").validate(paper)
            assert paper["primaryDomain"] == "colorectal-oncology"
            assert paper["secondaryDomains"] == ["surgical-intelligence"]
            assert paper["subtopics"] == ["mcrc-braf-v600e", "surgical-risk-prediction"]

            for slug in ("colorectal-oncology", "surgical-intelligence"):
                listed = all_pages(client, "/papers", domain=slug, limit=100)
                assert [p["id"] for p in listed if p["id"] == target] == [target]
                assert get(client, f"/domains/{slug}")["paperCount"] >= 1
        finally:
            conn.execute("delete from app.paper_domains where paper_id = %s and assigned_by = 'test'", (target,))


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

    domain_hits = all_pages(client, "/search", q="大腸直腸腫瘤")
    assert any(h["kind"] == "paper" and h["id"] == paper["id"] for h in domain_hits)
    en_hits = all_pages(client, "/search", q="Colorectal Oncology")
    assert any(h["kind"] == "paper" and h["id"] == paper["id"] for h in en_hits)


def test_search_treats_wildcards_literally(client: TestClient) -> None:
    assert get(client, "/search", q="%%")["items"] == []
    assert get(client, "/search", q="__")["items"] == []


def test_search_uses_pg_trgm_indexes(client: TestClient) -> None:
    """K7 #257: verify the planner uses the partial GIN pg_trgm indexes on app.public_papers and app.public_news."""
    assert DB_URL
    with psycopg.connect(API_URL) as conn, conn.transaction():
        conn.execute("set local enable_seqscan = off")
        paper_plan = "\n".join(
            row[0] for row in conn.execute("explain select id from app.public_papers where search_text like '%beacon%'")
        )
        news_plan = "\n".join(
            row[0] for row in conn.execute("explain select id from app.public_news where search_text like '%niche%'")
        )
    assert "papers_search_text_trgm_idx" in paper_plan, paper_plan
    assert "news_search_text_trgm_idx" in news_plan, news_plan


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
            assert client.get(f"{API_PREFIX}/papers/by-slug/{target.lower().replace('_', '-')}").status_code == 404
            papers = all_pages(client, "/papers", limit=100)
            assert target not in {p["id"] for p in papers}
            assert all(r["targetId"] != target for p in papers for r in p["relations"])
            assert all(h["id"] != target for h in all_pages(client, "/search", q=target))
        finally:
            conn.execute("update app.papers set withdrawn_at = null where id = %s", (target,))


def test_a_paper_summary_is_returned_as_written(client: TestClient) -> None:
    """I1 #190: the at-a-glance summary is plain data from papers.summary, checked against the contract."""
    target = next(iter(RAW_PAPERS))
    summary = {
        "title": "標題", "takeaway": "一句話", "question": "問題", "population": "病人", "comparison": "比較",
        "findings": ["結果"], "meaning": "意義", "limits": ["限制"], "model": "claude-fable-5-2",
        "writtenAt": "2026-11-19", "reviewedAt": None,
    }  # fmt: skip
    assert DB_URL
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("update app.papers set summary = %s where id = %s", (Jsonb(summary), target))
        try:
            paper = get(client, f"/papers/{target}")
            schema("Paper").validate(paper)
            assert paper["summary"] == summary
        finally:
            conn.execute("update app.papers set summary = null where id = %s", (target,))
    assert "summary" not in get(client, f"/papers/{target}")


# --- errors --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "status", "code"),
    [
        ("/papers/does-not-exist", 404, "not_found"),
        ("/news/does-not-exist", 404, "not_found"),
        ("/news-events/does-not-exist", 404, "not_found"),
        ("/news-events/INVALID_ID", 422, "validation_error"),
        ("/news-events?domain=not-a-domain", 422, "validation_error"),
        ("/news-events?category=not-a-category", 422, "validation_error"),
        ("/topics/not-a-topic", 422, "validation_error"),
        ("/papers?topic=not-a-topic", 422, "validation_error"),
        ("/domains/not-a-domain", 422, "validation_error"),
        ("/papers?domain=not-a-domain", 422, "validation_error"),
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
        row = conn.execute(
            "select n.dek, p.bottom_line from app.news n join app.papers p on p.id = n.paper_id where n.id = %s",
            (news_id,),
        ).fetchone()
        assert row is not None
        expected_conclusion = (row[0] or "").strip() or row[1]
        kinds = {c.kind for c in collect(conn, day)}
    assert "news" in kinds

    response = client.get(f"{API_PREFIX}/daily-pick", params={"date": day.isoformat()})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    schema("DailyPick").validate(body)
    pick = body["pick"]
    assert pick["kind"] == "news" and pick["date"] == day.isoformat()
    assert pick["url"].startswith("/news/") and pick["conclusion"] == expected_conclusion


def test_daily_pick_is_empty_on_a_day_without_new_content(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/daily-pick", params={"date": "2001-01-01"})
    assert response.status_code == 200
    assert response.json() == {"date": "2001-01-01", "pick": None}
    assert client.get(f"{API_PREFIX}/daily-pick", params={"date": "yesterday"}).status_code == 422


def test_daily_pick_can_fall_back_to_the_latest_day_with_one(client: TestClient) -> None:
    assert DB_URL
    with psycopg.connect(DB_URL) as conn:
        latest = conn.execute("select max(published_at) from app.public_news").fetchone()
    assert latest is not None and latest[0] is not None
    later = (latest[0] + timedelta(days=400)).isoformat()
    body = client.get(f"{API_PREFIX}/daily-pick", params={"date": later, "recent": "true"}).json()
    schema("DailyPick").validate(body)
    assert body["date"] == later
    assert body["pick"] is not None and body["pick"]["date"] <= later
    # Without recent, the same day has nothing; and nothing earlier than the first entry exists either way.
    assert client.get(f"{API_PREFIX}/daily-pick", params={"date": later}).json()["pick"] is None
    first = client.get(f"{API_PREFIX}/daily-pick", params={"date": "2001-01-01", "recent": "true"}).json()
    assert first["pick"] is None
