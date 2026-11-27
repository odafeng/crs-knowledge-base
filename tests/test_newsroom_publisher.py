"""Unit and PostgreSQL integration tests for N5 #290: Controlled Publisher, append-only revisions, audit log, and feature flags."""

import os

import pytest
from newsroom.publisher import NewsroomFlags, PublisherError, apply_review_action

DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")


def test_four_independent_feature_flags_default_safely_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "NEWSROOM_COLLECT_ENABLED",
        "NEWSROOM_DRAFT_ENABLED",
        "NEWSROOM_AUTO_PUBLISH_ENABLED",
        "NEWSROOM_NOTIFY_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)
    flags = NewsroomFlags.from_env()
    assert flags.collect_enabled is False
    assert flags.draft_enabled is False
    assert flags.auto_publish_enabled is False
    assert flags.notify_enabled is False

    monkeypatch.setenv("NEWSROOM_COLLECT_ENABLED", "true")
    monkeypatch.setenv("NEWSROOM_DRAFT_ENABLED", "1")
    partial = NewsroomFlags.from_env()
    assert partial.collect_enabled is True
    assert partial.draft_enabled is True
    assert partial.auto_publish_enabled is False
    assert partial.notify_enabled is False


def test_auto_publish_fails_closed_when_flag_disabled() -> None:
    with pytest.raises(PublisherError, match="NEWSROOM_AUTO_PUBLISH_ENABLED"):
        apply_review_action(
            None,
            event_id="evt-1",
            action="auto_publish",
            actor_label="system",
            reason="auto",
            idempotency_key="k-auto-1",
            flags=NewsroomFlags(auto_publish_enabled=False),
        )


@pytest.mark.skipif(not DB_URL and os.environ.get("GUTHUB_REQUIRE_DB") != "1", reason="no test database")
def test_controlled_publisher_lifecycle_revisions_idempotency_and_revalidation() -> None:
    if not DB_URL:
        pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    import psycopg

    revalidations = 0

    def on_revalidate() -> None:
        nonlocal revalidations
        revalidations += 1

    with psycopg.connect(DB_URL) as conn, conn.transaction(force_rollback=True):
        conn.execute(
            "insert into app.news_events"
            " (id, dedup_key, category, geography, evidence_status, risk_tier, status, published_at) values"
            " ('n5-evt', 'dk-n5-evt', 'regulatory', 'taiwan', 'approved', 'high', 'pending_review', '2026-11-28')"
        )
        r1 = conn.execute(
            "insert into app.news_revisions"
            " (event_id, revision_number, headline, what_happened, why_it_matters, clinical_relevance,"
            "  evidence_limitations, created_by) values"
            " ('n5-evt', 1, 'Initial headline', 'w1', 'y1', 'c1', 'l1', 'drafter') returning id"
        ).fetchone()
        assert r1 is not None
        conn.execute("update app.news_events set current_revision_id = %s where id = 'n5-evt'", (r1[0],))
        conn.execute(
            "insert into app.news_claims (revision_id, claim_text, evidence_quote, source_url, verified) values"
            " (%s, 'claim 1', 'quote 1', 'https://info.nhi.gov.tw/1', true)",
            (r1[0],),
        )

        # High-risk event cannot auto-publish even if flag is enabled.
        with pytest.raises(PublisherError, match="only low-risk"):
            apply_review_action(
                conn,
                event_id="n5-evt",
                action="auto_publish",
                actor_label="system",
                reason="try auto",
                idempotency_key="n5-auto-fail",
                flags=NewsroomFlags(auto_publish_enabled=True),
            )

        # Approve publishes to app.public_news_events and triggers revalidation.
        approved = apply_review_action(
            conn,
            event_id="n5-evt",
            action="approve",
            actor_label="maintainer",
            reason="verified against NHI PDF",
            idempotency_key="n5-approve-1",
            revalidate_fn=on_revalidate,
        )
        assert approved["idempotent_replay"] is False
        assert revalidations == 1
        assert conn.execute("select headline from app.public_news_events where id = 'n5-evt'").fetchone() == (
            "Initial headline",
        )

        # Replay with same idempotency_key is a clean no-op (no duplicate audit row or revalidation).
        replay = apply_review_action(
            conn,
            event_id="n5-evt",
            action="approve",
            actor_label="maintainer",
            reason="verified against NHI PDF",
            idempotency_key="n5-approve-1",
            revalidate_fn=on_revalidate,
        )
        assert replay["idempotent_replay"] is True
        assert revalidations == 1

        # Revise appends revision #2 while preserving revision #1 and carrying claims forward.
        apply_review_action(
            conn,
            event_id="n5-evt",
            action="revise",
            actor_label="maintainer",
            reason="clarified effective date",
            idempotency_key="n5-revise-1",
            revision_payload={"headline": "Corrected headline", "correction_note": "修正生效日期為 2026-12-01"},
            revalidate_fn=on_revalidate,
        )
        assert revalidations == 2
        rev_nums = conn.execute(
            "select revision_number from app.news_revisions where event_id = 'n5-evt' order by revision_number"
        ).fetchall()
        assert rev_nums == [(1,), (2,)]
        pub = conn.execute(
            "select headline, revision_number, correction_note, review_status"
            " from app.public_news_events where id = 'n5-evt'"
        ).fetchone()
        assert pub == ("Corrected headline", 2, "修正生效日期為 2026-12-01", "revised")

        # Withdraw immediately excludes the event from app.public_news_events and triggers revalidation.
        apply_review_action(
            conn,
            event_id="n5-evt",
            action="withdraw",
            actor_label="maintainer",
            reason="superseded by updated announcement",
            idempotency_key="n5-withdraw-1",
            revalidate_fn=on_revalidate,
        )
        assert revalidations == 3
        assert conn.execute("select 1 from app.public_news_events where id = 'n5-evt'").fetchone() is None

        actions = conn.execute(
            "select action from app.news_review_actions where event_id = 'n5-evt' order by created_at, id"
        ).fetchall()
        # All three actions run inside one test transaction (identical now() timestamps), so assert exact multiset.
        assert sorted(a[0] for a in actions) == ["approve", "revise", "withdraw"]
