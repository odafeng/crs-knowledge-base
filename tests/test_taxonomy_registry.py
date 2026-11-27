"""Parity and fail-closed validation tests for the Central Topic Registry (T1 #282, ADR-0030)."""

import json
import re
from pathlib import Path

import pytest
import yaml

from taxonomy_registry import TaxonomyError, load_registry
from topics import ALL_TOPIC_KEYS

ROOT = Path(__file__).resolve().parent.parent


def test_api_copy_matches_canonical_taxonomy_registry() -> None:
    canonical = json.loads((ROOT / "contracts/taxonomy.json").read_text(encoding="utf-8"))
    api_copy = json.loads((ROOT / "apps/api/src/guthub_api/taxonomy.json").read_text(encoding="utf-8"))
    assert api_copy == canonical, "copy contracts/taxonomy.json to apps/api/src/guthub_api/taxonomy.json"


def test_openapi_and_web_generated_domains_match_registry() -> None:
    registry = load_registry()
    spec = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text(encoding="utf-8"))
    openapi_domains = tuple(spec["components"]["schemas"]["DomainSlug"]["enum"])
    assert openapi_domains == registry.domain_slugs
    assert len(registry.domains) == 8

    web_ts = (ROOT / "apps/web/src/lib/taxonomy.generated.ts").read_text(encoding="utf-8")
    assert f'TAXONOMY_VERSION = "{registry.version}"' in web_ts
    for slug in registry.domain_slugs:
        assert f'"{slug}"' in web_ts


def test_migration_seeds_all_registry_domains_and_subtopics() -> None:
    registry = load_registry()
    migration = (ROOT / "supabase/migrations/20261127000000_taxonomy_registry.sql").read_text(encoding="utf-8")
    for domain in registry.domains:
        assert f"'{domain.slug}'" in migration
    for subtopic in registry.subtopics:
        assert f"'{subtopic.id}'" in migration


def test_all_legacy_topic_keys_have_explicit_compatibility_aliases() -> None:
    registry = load_registry()
    assert set(registry.aliases) == ALL_TOPIC_KEYS
    for key in ("mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H", "mCRC-HER2", "mCRC-RAS-wt"):
        alias = registry.resolve_legacy_key(key)
        assert alias.domain == "colorectal-oncology"
        assert alias.policy == "direct"
        assert alias.subtopic is not None
    robotic = registry.resolve_legacy_key("robotic-surgery")
    assert robotic.domain == "minimally-invasive-surgery"
    assert robotic.policy == "default_candidate"
    generic = registry.resolve_legacy_key("generic-CRS")
    assert generic.domain is None
    assert generic.policy == "manual_review_required"


def test_controlled_tags_are_sorted_unique_kebab_case() -> None:
    raw = json.loads((ROOT / "contracts/taxonomy.json").read_text(encoding="utf-8"))
    tags = raw["tags"]
    assert tags == sorted(set(tags))
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", tag) for tag in tags)


def test_multi_domain_assignment_accepts_valid_cross_domain_paper() -> None:
    registry = load_registry()
    result = registry.validate_assignment(
        primary_domain="surgical-intelligence",
        secondary_domains=("minimally-invasive-surgery", "perioperative-care-nutrition", "colorectal-oncology"),
        subtopics=("surgical-risk-prediction", "anastomotic-leak-stoma"),
        tags=("robotic-tme", "anastomotic-leakage", "risk-prediction", "deep-learning"),
        taxonomy_version="1.0",
    )
    assert result["primary_domain"] == "surgical-intelligence"
    assert len(result["secondary_domains"]) == 3


@pytest.mark.parametrize(
    ("kwargs", "pattern"),
    [
        ({"primary_domain": "unknown-domain"}, "unknown or inactive domain"),
        ({"primary_domain": "endoscopy", "taxonomy_version": "2.0"}, "unsupported taxonomy_version"),
        (
            {"primary_domain": "endoscopy", "secondary_domains": ("endoscopy",)},
            "cannot repeat primary_domain",
        ),
        (
            {"primary_domain": "endoscopy", "secondary_domains": ("surgical-intelligence", "surgical-intelligence")},
            "duplicate secondary domain",
        ),
        (
            {"primary_domain": "endoscopy", "subtopics": ("mcrc-braf-v600e",)},
            "not in assigned domains",
        ),
        (
            {"primary_domain": "endoscopy", "subtopics": ("no-such-subtopic",)},
            "unknown subtopic",
        ),
        (
            {"primary_domain": "endoscopy", "tags": ("invented-tag",)},
            "unknown controlled tag",
        ),
    ],
)
def test_assignment_fails_closed_on_invalid_inputs(kwargs: dict, pattern: str) -> None:
    registry = load_registry()
    with pytest.raises(TaxonomyError, match=pattern):
        registry.validate_assignment(**kwargs)


def test_unknown_legacy_key_fails_closed() -> None:
    registry = load_registry()
    with pytest.raises(TaxonomyError, match="unknown legacy topic key"):
        registry.resolve_legacy_key("unknown-topic")
