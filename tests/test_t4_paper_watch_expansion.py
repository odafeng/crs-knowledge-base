"""Tests for T4 #285: 8-specialty Paper Watch query packs, shadow gating, and cross-domain canonical dedup."""

from unittest.mock import patch

import fetch_pubmed as fp
import fetch_rss as fr
from classify import MAX_REPAIR_ATTEMPTS
from config import load_queries
from main import deduplicate_candidates
from publish import AUTO_PUBLISH_TOPICS
from taxonomy_registry import load_registry
from topic_agents import build_system_prompt

NEW_BATCHES = {
    1: {"perioperative-care-nutrition", "endoscopy"},
    2: {"anorectal-diseases", "benign-colorectal-diseases"},
    3: {"pelvic-floor-functional", "surgical-intelligence"},
}


def test_every_query_pack_references_valid_registry_domain_and_shadows_new_batches() -> None:
    registry = load_registry()
    queries = load_queries()
    topic_packs = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}

    covered_domains = set()
    for key, cfg in topic_packs.items():
        domain = cfg.get("domain")
        assert domain in registry.active_domain_slugs, f"{key} missing valid registry domain"
        covered_domains.add(domain)
        assert "[tiab]" in cfg["pubmed_query"], f"{key} pubmed_query must include [tiab]"
        assert cfg["keywords"], f"{key} must define keywords"
        assert cfg["rss_filter_terms"], f"{key} must define rss_filter_terms"

    # All 8 clinical specialties are covered across active + shadow packs.
    assert covered_domains == set(registry.active_domain_slugs)

    for batch_num, expected_domains in NEW_BATCHES.items():
        found = {k for k, cfg in topic_packs.items() if cfg.get("rollout_batch") == batch_num}
        assert found == expected_domains
        for key in expected_domains:
            assert topic_packs[key]["shadow_only"] is True
            assert key not in AUTO_PUBLISH_TOPICS
            assert len(build_system_prompt(key)) > 400


def test_shadow_packs_are_excluded_by_default_and_selectable_by_batch_or_topic() -> None:
    queries = load_queries()
    default_topics = fp._select_topics(queries)
    for domains in NEW_BATCHES.values():
        assert not (set(default_topics) & domains)

    assert set(fp._select_topics(queries, shadow_batch=1)) == NEW_BATCHES[1]
    assert set(fp._select_topics(queries, shadow_batch=2)) == NEW_BATCHES[2]
    assert set(fp._select_topics(queries, shadow_batch=3)) == NEW_BATCHES[3]
    assert fp._select_topics(queries, topic="endoscopy") == ["endoscopy"]

    active_rss = fr._active_topics(queries)
    assert "endoscopy" not in active_rss
    assert "endoscopy" in fr._active_topics(queries, include_shadow=True)


def test_cross_specialty_paper_creates_single_canonical_candidate_with_secondary_domains() -> None:
    sample_article = {
        "pmid": "99900001",
        "doi": "10.1000/ai-tme-leak",
        "title": "Deep learning pelvimetry predicts anastomotic leak in robotic TME",
        "authors": "Lin C",
        "journal": "Ann Surg",
        "year": "2026",
        "abstract": "Multicenter external validation of AI model for robotic TME anastomotic leak.",
        "source": "pubmed",
    }
    mock_queries = {
        "robotic-surgery": {
            "domain": "minimally-invasive-surgery",
            "pubmed_query": "q1[tiab]",
            "keywords": ["robotic", "TME"],
            "rss_filter_terms": ["robotic", "TME"],
            "shadow_only": False,
        },
        "surgical-intelligence": {
            "domain": "surgical-intelligence",
            "pubmed_query": "q2[tiab]",
            "keywords": ["deep learning", "pelvimetry"],
            "rss_filter_terms": ["deep learning", "pelvimetry"],
            "shadow_only": True,
        },
        "perioperative-care-nutrition": {
            "domain": "perioperative-care-nutrition",
            "pubmed_query": "q3[tiab]",
            "keywords": ["anastomotic leak"],
            "rss_filter_terms": ["anastomotic leak"],
            "shadow_only": True,
        },
    }

    with (
        patch("fetch_pubmed.load_queries", return_value=mock_queries),
        patch("fetch_pubmed.load_tracked_dois", return_value={}),
        patch("fetch_pubmed.esearch", return_value=["99900001"]),
        patch("fetch_pubmed.efetch", side_effect=lambda _: [dict(sample_article)]),
        patch("fetch_pubmed._is_conference_season", return_value=(False, None)),
        patch("fetch_pubmed.time.sleep"),
    ):
        candidates = fp.fetch_pubmed(include_shadow=True)

    assert len(candidates) == 1
    assert candidates[0]["primary_domain"] == "minimally-invasive-surgery"
    assert candidates[0]["secondary_domains"] == ["surgical-intelligence", "perioperative-care-nutrition"]

    # Cross-source dedup in main.py also merges domains onto the single canonical candidate.
    merged = deduplicate_candidates(
        [
            {
                "doi": "10.1000/cross",
                "title": "Journal version",
                "source": "journal",
                "primary_domain": "perioperative-care-nutrition",
                "secondary_domains": [],
            },
            {
                "doi": "10.1000/cross",
                "title": "PubMed version",
                "source": "pubmed",
                "primary_domain": "minimally-invasive-surgery",
                "secondary_domains": ["surgical-intelligence"],
            },
        ]
    )
    assert len(merged) == 1
    assert merged[0]["title"] == "PubMed version"
    assert merged[0]["primary_domain"] == "minimally-invasive-surgery"
    assert merged[0]["secondary_domains"] == ["surgical-intelligence", "perioperative-care-nutrition"]


def test_unmatched_journal_articles_are_recorded_instead_of_dumped_into_generic_crs() -> None:
    unmatched: list[dict] = []
    mock_queries = {
        "generic-CRS": {
            "domain": "colorectal-oncology",
            "rss_filter_terms": ["fruquintinib", "colorectal"],
            "shadow_only": False,
        },
        "rss_feeds": [{"name": "BJS", "pubmed_journal": "Br J Surg"}],
    }
    with (
        patch("fetch_rss.load_queries", return_value=mock_queries),
        patch("fetch_rss.load_tracked_dois", return_value={}),
        patch("fetch_rss.esearch", return_value=["555"]),
        patch(
            "fetch_rss.efetch",
            return_value=[{"pmid": "555", "doi": "10.1000/misc", "title": "Hospital staffing survey", "abstract": ""}],
        ),
        patch("fetch_rss.time.sleep"),
    ):
        results = fr.fetch_rss(unmatched_out=unmatched)
    assert results == []
    assert len(unmatched) == 1
    assert unmatched[0]["pmid"] == "555"


def test_adr_0013_and_adr_0029_guardrails_remain_intact() -> None:
    assert MAX_REPAIR_ATTEMPTS == 2
    assert len(AUTO_PUBLISH_TOPICS) == 7
