"""Unit and DB integration tests for N1 #286: Newsroom core schema, RLS isolation, and ChatGPT intake adapter."""

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "worker"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import content_requests as cr  # noqa: E402
from newsroom.intake import (  # noqa: E402
    MAX_PAYLOAD_BYTES,
    IntakeValidationError,
    ingest_batch,
    parse_intake_body,
)

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")

LIVE_ISSUE_280_BODY = """\
PoC test issue from ChatGPT News Radar.

```json
{
  "schema_version": "1.0",
  "producer": "chatgpt-news-radar",
  "batch_id": "guthub-poc-2026-11-27",
  "test_mode": true,
  "publish_allowed": false,
  "items": []
}
```
"""

SYNTHETIC_V11_BODY = """\
Synthetic non-empty v1.1 batch.

```json
{
  "schema_version": "1.1",
  "taxonomy_version": "1.0",
  "producer": "chatgpt-news-radar",
  "batch_id": "guthub-synth-2026-11-28",
  "test_mode": false,
  "publish_allowed": true,
  "items": [
    {
      "external_id": "fda-2026-crc-01",
      "title": "FDA grants approval for novel BRAF regimen in mCRC",
      "canonical_url": "https://www.fda.gov/drugs/example-mcrc-2026",
      "event_type": "regulatory",
      "published_at": "2026-11-28",
      "event_date": "2026-11-28",
      "primary_domain_hint": "colorectal-oncology",
      "secondary_domain_hints": ["surgical-intelligence"]
    }
  ]
}
```
"""


def test_parses_live_issue_280_v10_as_isolated_test() -> None:
    batch = parse_intake_body(LIVE_ISSUE_280_BODY)
    assert batch.schema_version == "1.0"
    assert batch.producer == "chatgpt-news-radar"
    assert batch.batch_id == "guthub-poc-2026-11-27"
    assert batch.test_mode is True
    assert batch.publish_allowed is False
    assert batch.is_isolated_test is True
    assert batch.items == ()
    assert len(batch.payload_hash) == 64


def test_parses_synthetic_non_empty_v11_batch() -> None:
    batch = parse_intake_body(SYNTHETIC_V11_BODY)
    assert batch.schema_version == "1.1"
    assert batch.taxonomy_version == "1.0"
    assert batch.is_isolated_test is False
    assert len(batch.items) == 1
    item = batch.items[0]
    assert item["canonical_url"] == "https://www.fda.gov/drugs/example-mcrc-2026"
    assert item["primary_domain_hint"] == "colorectal-oncology"
    assert item["secondary_domain_hints"] == ["surgical-intelligence"]


def test_fail_closed_when_test_mode_or_publish_allowed_blocks_ingestion() -> None:
    for test_mode, publish_allowed, expected_isolated in (
        (True, True, True),
        (False, False, True),
        (True, False, True),
        (False, True, False),
    ):
        body = f"""```json
{
            json.dumps(
                {
                    "schema_version": "1.0",
                    "producer": "chatgpt-news-radar",
                    "batch_id": "b1",
                    "test_mode": test_mode,
                    "publish_allowed": publish_allowed,
                    "items": [],
                }
            )
        }
```"""
        assert parse_intake_body(body).is_isolated_test is expected_isolated


def test_rejects_duplicate_keys_multiple_blocks_oversize_and_bad_versions() -> None:
    dup_key = '```json\n{"schema_version":"1.0","producer":"p","batch_id":"b","test_mode":false,"test_mode":true,"publish_allowed":false,"items":[]}\n```'
    with pytest.raises(IntakeValidationError, match="duplicate JSON key"):
        parse_intake_body(dup_key)

    two_blocks = "```json\n{}\n```\n\n```json\n{}\n```"
    with pytest.raises(IntakeValidationError, match="exactly 1 required"):
        parse_intake_body(two_blocks)

    with pytest.raises(IntakeValidationError, match="no fenced"):
        parse_intake_body("plain text without json")

    huge = '```json\n{"schema_version":"1.0","pad":"' + ("a" * (MAX_PAYLOAD_BYTES + 100)) + '"}\n```'
    with pytest.raises(IntakeValidationError, match="exceeds"):
        parse_intake_body(huge)

    bad_tax = SYNTHETIC_V11_BODY.replace('"taxonomy_version": "1.0"', '"taxonomy_version": "9.9"')
    with pytest.raises(IntakeValidationError, match="unsupported taxonomy_version"):
        parse_intake_body(bad_tax)


def test_content_requests_ignores_news_candidate_and_chatgpt_source_issues() -> None:
    issues = [
        {
            "number": 280,
            "title": "ChatGPT News Radar PoC",
            "body": LIVE_ISSUE_280_BODY,
            "user": {"login": "odafeng"},
            "labels": [{"name": "accepted"}, {"name": "news-candidate"}],
        },
        {
            "number": 281,
            "title": "ChatGPT News Radar Batch",
            "body": SYNTHETIC_V11_BODY,
            "user": {"login": "odafeng"},
            "labels": [{"name": "accepted"}, {"name": "source:chatgpt"}],
        },
        {
            "number": 282,
            "title": "[撤下] something",
            "body": "",
            "user": {"login": "github-actions[bot]"},
            "labels": [{"name": "unpublish-request"}, {"name": "news-candidate"}],
        },
        {
            "number": 283,
            "title": "Real Paper Watch accept",
            "body": "<!-- paper-data\n{}\n-->",
            "user": {"login": "odafeng"},
            "labels": [{"name": "accepted"}],
        },
    ]
    accepts, unpublishes = cr.pending(issues, owner="odafeng")
    assert [i["number"] for i in accepts] == [283]
    assert unpublishes == []


@pytest.mark.skipif(not DB_URL and os.environ.get("GUTHUB_REQUIRE_DB") != "1", reason="no test database")
def test_newsroom_db_isolation_idempotency_conflict_and_rls() -> None:
    if not DB_URL:
        pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    import psycopg
    from psycopg import errors

    with psycopg.connect(DB_URL) as conn, conn.transaction(force_rollback=True):
        # 1. Live #280 test_mode=true batch is isolated and creates 0 candidates.
        poc_batch = parse_intake_body(LIVE_ISSUE_280_BODY)
        res_poc = ingest_batch(conn, poc_batch, source_repo="odafeng/guthub-news-inbox", source_issue_number=1)
        assert res_poc["outcome"] == "isolated_test"
        assert res_poc["candidates_inserted"] == 0
        count = conn.execute("select count(*) from app.news_candidates").fetchone()
        assert count is not None and count[0] == 0

        # 2. Non-empty v1.1 batch ingests once, re-ingest is idempotent no-op, edited hash isolates conflict.
        v11 = parse_intake_body(SYNTHETIC_V11_BODY)
        first = ingest_batch(conn, v11, source_repo="odafeng/guthub-news-inbox", source_issue_number=2)
        assert first["outcome"] == "ingested"
        assert first["candidates_inserted"] == 1

        again = ingest_batch(conn, v11, source_repo="odafeng/guthub-news-inbox", source_issue_number=2)
        assert again["outcome"] == "duplicate_noop"
        assert again["candidates_inserted"] == 0

        edited = parse_intake_body(SYNTHETIC_V11_BODY.replace("novel BRAF regimen", "edited title"))
        conflict = ingest_batch(conn, edited, source_repo="odafeng/guthub-news-inbox", source_issue_number=2)
        assert conflict["outcome"] == "conflict"
        assert conflict["candidates_inserted"] == 0

        # 3. Draft vs published visibility + single-primary domain constraint.
        conn.execute(
            "insert into app.news_events"
            " (id, dedup_key, category, geography, evidence_status, risk_tier, status, published_at) values"
            " ('draft-evt', 'dk-draft', 'regulatory', 'us', 'approved', 'high', 'draft', '2026-11-28'),"
            " ('pub-evt', 'dk-pub', 'regulatory', 'taiwan', 'approved', 'low', 'published', '2026-11-28')"
        )
        rev_draft = conn.execute(
            "insert into app.news_revisions"
            " (event_id, revision_number, headline, what_happened, why_it_matters, clinical_relevance,"
            "  evidence_limitations, created_by) values"
            " ('draft-evt', 1, 'Draft headline', 'w', 'y', 'c', 'l', 'test') returning id"
        ).fetchone()
        rev_pub = conn.execute(
            "insert into app.news_revisions"
            " (event_id, revision_number, headline, what_happened, why_it_matters, clinical_relevance,"
            "  evidence_limitations, created_by) values"
            " ('pub-evt', 1, 'Published headline', 'w', 'y', 'c', 'l', 'test') returning id"
        ).fetchone()
        assert rev_draft and rev_pub
        conn.execute("update app.news_events set current_revision_id = %s where id = 'draft-evt'", (rev_draft[0],))
        conn.execute("update app.news_events set current_revision_id = %s where id = 'pub-evt'", (rev_pub[0],))
        conn.execute(
            "insert into app.news_event_domains (event_id, domain_slug, is_primary, taxonomy_version) values"
            " ('pub-evt', 'colorectal-oncology', true, '1.0'),"
            " ('pub-evt', 'surgical-intelligence', false, '1.0')"
        )
        with conn.transaction(force_rollback=True), pytest.raises(errors.UniqueViolation):
            conn.execute(
                "insert into app.news_event_domains (event_id, domain_slug, is_primary, taxonomy_version) values"
                " ('pub-evt', 'endoscopy', true, '1.0')"
            )

        # 4. Role isolation matrix: guthub_api can ONLY read public views and gets permission denied on internal tables.
        with conn.transaction(force_rollback=True):
            conn.execute("set local role guthub_api")
            pub_rows = conn.execute(
                "select id, primary_domain, secondary_domains from app.public_news_events"
            ).fetchall()
            assert pub_rows == [("pub-evt", "colorectal-oncology", ["surgical-intelligence"])]
            conn.execute("select * from app.public_news_source_health").fetchall()

            for forbidden in (
                "news_events",
                "news_revisions",
                "news_ingest_batches",
                "news_candidates",
                "news_claims",
                "news_review_actions",
                "news_runs",
            ):
                with conn.transaction(force_rollback=True), pytest.raises(errors.InsufficientPrivilege):
                    conn.execute(f"select * from app.{forbidden}").fetchall()
