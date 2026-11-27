"""Unit and DB integration tests for T2 #283 taxonomy dry-run manifest, backfill, and verification."""

import copy
import os
import shutil
from pathlib import Path

import content_writer
import pytest
from import_content import apply, build_rows

from content_store import content_session
from publish import publish_paper
from taxonomy_backfill import (
    BackfillError,
    apply_manifest,
    build_manifest,
    classify_paper,
    load_papers_from_db,
    load_papers_from_json,
    validate_manifest_for_apply,
    verify_backfill,
)
from taxonomy_registry import load_registry
from test_publish import TODAY, _paper

ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.environ.get("GUTHUB_TEST_DATABASE_URL")


def test_dry_run_manifest_from_local_json_is_deterministic_and_flags_generic_crs() -> None:
    registry = load_registry()
    papers = load_papers_from_json()
    first = build_manifest(papers, registry)
    second = build_manifest(papers, registry)
    assert first == second
    assert first["summary"]["total"] == len(papers)
    assert first["summary"]["ambiguous"] == 0

    by_id = {entry["paper_id"]: entry for entry in first["entries"]}
    # Direct mCRC aliases map cleanly without manual review.
    assert by_id["beacon-2019"]["proposed_primary_domain"] == "colorectal-oncology"
    assert by_id["beacon-2019"]["proposed_subtopic_id"] == "mcrc-braf-v600e"
    assert by_id["beacon-2019"]["needs_review"] is False

    # Every generic-CRS entry must require explicit maintainer sign-off (ADR-0030).
    generic_entries = [e for e in first["entries"] if e["legacy_topic_key"] == "generic-CRS"]
    assert len(generic_entries) == 11
    assert all(e["needs_review"] is True for e in generic_entries)
    assert all(e["proposed_primary_domain"] == "colorectal-oncology" for e in generic_entries)


def test_robotic_ai_and_ambiguous_generic_papers_are_flagged_for_review() -> None:
    registry = load_registry()
    ai_robotic = classify_paper(
        {
            "id": "ai-tme-2026",
            "topic_key": "robotic-surgery",
            "regimen": "Deep learning CT pelvimetry for robotic TME anastomotic leakage prediction",
            "bottom_line": "Predicts anastomotic leak after robotic TME",
        },
        registry,
    )
    assert ai_robotic["proposed_primary_domain"] == "minimally-invasive-surgery"
    assert "surgical-intelligence" in ai_robotic["proposed_secondary_domains"]
    assert "perioperative-care-nutrition" in ai_robotic["proposed_secondary_domains"]
    assert ai_robotic["needs_review"] is True

    ambiguous = classify_paper(
        {
            "id": "misc-crs-2026",
            "topic_key": "generic-CRS",
            "regimen": "Novel outpatient bowel preparation protocol",
            "bottom_line": "Improved patient tolerance",
        },
        registry,
    )
    assert ambiguous["proposed_primary_domain"] is None
    assert ambiguous["confidence"] == "ambiguous"
    assert ambiguous["needs_review"] is True


def test_validate_manifest_fails_closed_on_unreviewed_or_ambiguous_entries() -> None:
    registry = load_registry()
    manifest_doc = build_manifest(load_papers_from_json(), registry)
    # Local JSON contains generic-CRS entries with needs_review=True and reviewed=False.
    with pytest.raises(BackfillError, match="needs_review is true"):
        validate_manifest_for_apply(manifest_doc, registry)

    approved = copy.deepcopy(manifest_doc)
    for entry in approved["entries"]:
        if entry["needs_review"]:
            entry["reviewed"] = True
    validated = validate_manifest_for_apply(approved, registry)
    assert len(validated) == len(manifest_doc["entries"])

    bad_version = {**approved, "taxonomy_version": "9.9"}
    with pytest.raises(BackfillError, match="unsupported taxonomy_version"):
        validate_manifest_for_apply(bad_version, registry)


@pytest.mark.skipif(not DB_URL and os.environ.get("GUTHUB_REQUIRE_DB") != "1", reason="no test database")
def test_backfill_apply_is_idempotent_verifies_and_survives_content_session(tmp_path: Path) -> None:
    if not DB_URL:
        pytest.fail("GUTHUB_REQUIRE_DB=1 but GUTHUB_TEST_DATABASE_URL is not set")
    import psycopg

    registry = load_registry()
    with psycopg.connect(DB_URL) as conn, conn.transaction(force_rollback=True):
        conn.execute(
            "truncate app.topics, app.papers, app.paper_relations, app.research_commentary, app.news,"
            " app.comments, app.comment_reports, app.moderation_events cascade"
        )
        conn.execute("truncate app.publish_events, app.paper_watch_state")
        conn.execute("update app.content_writer set writer = 'json', watermark = null")
        apply(conn, build_rows(ROOT))

        # Cutover to postgres writer mode so we also verify Single Content Writer coexistence.
        repo_copy = tmp_path / "repo"
        for name in ("data", "docs"):
            shutil.copytree(ROOT / name, repo_copy / name)
        (repo_copy / "data/WRITER").write_text("json\n", encoding="utf-8")
        content_writer.cutover(conn, repo_copy)

        db_papers = load_papers_from_db(conn)
        manifest_doc = build_manifest(db_papers, registry)
        for entry in manifest_doc["entries"]:
            if entry["needs_review"]:
                entry["reviewed"] = True

        # Snapshot existing papers/news counts to confirm zero unintended mutations.
        before_papers = conn.execute(
            "select id, slug, topic_key, doi, detail_html from app.papers order by id"
        ).fetchall()
        before_news = conn.execute("select id, paper_id from app.news order by id").fetchall()

        # Dry-run apply must roll back completely.
        dry_stats = apply_manifest(conn, manifest_doc, registry, dry_run=True)
        assert dry_stats["inserted"] == len(db_papers)
        assert verify_backfill(conn, registry)["ok"] is False

        # Real apply inserts all links; re-running is 100% idempotent (0 changes).
        first = apply_manifest(conn, manifest_doc, registry)
        assert first["inserted"] == len(db_papers)
        assert first["updated"] == 0 and first["removed"] == 0

        rerun = apply_manifest(conn, manifest_doc, registry)
        assert rerun["inserted"] == 0 and rerun["updated"] == 0 and rerun["removed"] == 0
        assert rerun["unchanged"] == len(db_papers)

        # Integrity verification passes and existing papers/news rows are untouched.
        report = verify_backfill(conn, registry)
        assert report["ok"] is True
        assert report["active_papers"] == len(db_papers)
        assert report["missing_primary"] == []
        assert (
            conn.execute("select id, slug, topic_key, doi, detail_html from app.papers order by id").fetchall()
            == before_papers
        )
        assert conn.execute("select id, paper_id from app.news order by id").fetchall() == before_news

        # Publishing a new paper through content_session preserves all backfilled app.paper_domains rows.
        new_paper = _paper(id="t2-compat-paper", doi="10.1000/t2-compat")
        with content_session("publish_paper", new_paper["doi"], key="t2-compat-key", conn=conn) as session:
            entry = publish_paper(new_paper, "auto", TODAY, **session.kb_args)
            session.record(f"publish {entry['id']}")
        preserved = conn.execute("select count(*) from app.paper_domains where is_primary = true").fetchone()
        assert preserved is not None and preserved[0] == len(db_papers)
