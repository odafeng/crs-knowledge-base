"""Shared loader and validator for the versioned Central Topic Registry (T1 #282, ADR-0030).

Reads contracts/taxonomy.json as the single source of truth for the 8 clinical specialty domains,
subtopics (including legacy TopicKey compatibility mappings), controlled tags, and aliases.
Unknown taxonomy versions or domain slugs always fail closed (raise TaxonomyError).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "contracts" / "taxonomy.json"


class TaxonomyError(ValueError):
    """Raised when a taxonomy version, domain slug, subtopic, or assignment fails validation."""


@dataclass(frozen=True)
class DomainDef:
    slug: str
    order: int
    label_zh: str
    label_en: str
    description_zh: str
    status: str


@dataclass(frozen=True)
class SubtopicDef:
    id: str
    parent_domain: str
    slug: str
    label_zh: str
    label_en: str
    legacy_topic_key: str | None
    route_path: str | None
    order: int
    status: str


@dataclass(frozen=True)
class AliasDef:
    key: str
    domain: str | None
    subtopic: str | None
    policy: str


@dataclass(frozen=True)
class TaxonomyRegistry:
    version: str
    domains: tuple[DomainDef, ...]
    subtopics: tuple[SubtopicDef, ...]
    tags: frozenset[str]
    aliases: dict[str, AliasDef]

    @property
    def domain_slugs(self) -> tuple[str, ...]:
        return tuple(d.slug for d in self.domains)

    @property
    def active_domain_slugs(self) -> frozenset[str]:
        return frozenset(d.slug for d in self.domains if d.status == "active")

    @property
    def subtopic_by_id(self) -> dict[str, SubtopicDef]:
        return {s.id: s for s in self.subtopics}

    @property
    def subtopic_by_legacy_key(self) -> dict[str, SubtopicDef]:
        return {s.legacy_topic_key: s for s in self.subtopics if s.legacy_topic_key is not None}

    def require_version(self, version: str) -> None:
        if version != self.version:
            raise TaxonomyError(f"unsupported taxonomy_version {version!r}; expected {self.version!r}")

    def require_domain(self, slug: str) -> DomainDef:
        for domain in self.domains:
            if domain.slug == slug and domain.status == "active":
                return domain
        raise TaxonomyError(f"unknown or inactive domain slug: {slug!r}")

    def validate_assignment(
        self,
        primary_domain: str,
        secondary_domains: list[str] | tuple[str, ...] = (),
        subtopics: list[str] | tuple[str, ...] = (),
        tags: list[str] | tuple[str, ...] = (),
        *,
        taxonomy_version: str | None = None,
    ) -> dict[str, Any]:
        """Validate a multi-domain classification assignment; fails closed on any unknown slug or duplicate."""
        if taxonomy_version is not None:
            self.require_version(taxonomy_version)
        self.require_domain(primary_domain)

        seen_secondary: list[str] = []
        for slug in secondary_domains:
            self.require_domain(slug)
            if slug == primary_domain:
                raise TaxonomyError(f"secondary_domains cannot repeat primary_domain {primary_domain!r}")
            if slug in seen_secondary:
                raise TaxonomyError(f"duplicate secondary domain: {slug!r}")
            seen_secondary.append(slug)

        allowed_domains = {primary_domain, *seen_secondary}
        subtopic_map = self.subtopic_by_id
        seen_subtopics: list[str] = []
        for sid in subtopics:
            sub = subtopic_map.get(sid)
            if sub is None:
                raise TaxonomyError(f"unknown subtopic id: {sid!r}")
            if sub.parent_domain not in allowed_domains:
                raise TaxonomyError(
                    f"subtopic {sid!r} belongs to {sub.parent_domain!r}, not in assigned domains {sorted(allowed_domains)}"
                )
            if sid in seen_subtopics:
                raise TaxonomyError(f"duplicate subtopic id: {sid!r}")
            seen_subtopics.append(sid)

        seen_tags: list[str] = []
        for tag in tags:
            if tag not in self.tags:
                raise TaxonomyError(f"unknown controlled tag: {tag!r}")
            if tag not in seen_tags:
                seen_tags.append(tag)

        return {
            "taxonomy_version": self.version,
            "primary_domain": primary_domain,
            "secondary_domains": tuple(seen_secondary),
            "subtopics": tuple(seen_subtopics),
            "tags": tuple(seen_tags),
        }

    def resolve_legacy_key(self, key: str) -> AliasDef:
        alias = self.aliases.get(key)
        if alias is None:
            raise TaxonomyError(f"unknown legacy topic key: {key!r}")
        return alias


def parse_registry(raw: dict[str, Any]) -> TaxonomyRegistry:
    version = str(raw["version"])
    domains = tuple(
        DomainDef(
            slug=d["slug"],
            order=int(d["order"]),
            label_zh=d["labelZh"],
            label_en=d["labelEn"],
            description_zh=d["descriptionZh"],
            status=d["status"],
        )
        for d in sorted(raw["domains"], key=lambda item: int(item["order"]))
    )
    domain_slugs = {d.slug for d in domains}
    if len(domain_slugs) != len(domains):
        raise TaxonomyError("duplicate domain slug in taxonomy registry")

    subtopics = tuple(
        SubtopicDef(
            id=s["id"],
            parent_domain=s["parentDomain"],
            slug=s["slug"],
            label_zh=s["labelZh"],
            label_en=s["labelEn"],
            legacy_topic_key=s.get("legacyTopicKey"),
            route_path=s.get("routePath"),
            order=int(s["order"]),
            status=s["status"],
        )
        for s in raw["subtopics"]
    )
    for sub in subtopics:
        if sub.parent_domain not in domain_slugs:
            raise TaxonomyError(f"subtopic {sub.id!r} references unknown parentDomain {sub.parent_domain!r}")

    aliases = {
        key: AliasDef(key=key, domain=val.get("domain"), subtopic=val.get("subtopic"), policy=val["policy"])
        for key, val in raw.get("aliases", {}).items()
    }
    return TaxonomyRegistry(
        version=version,
        domains=domains,
        subtopics=subtopics,
        tags=frozenset(raw.get("tags", ())),
        aliases=aliases,
    )


@lru_cache(maxsize=1)
def load_registry(path: Path = REGISTRY_PATH) -> TaxonomyRegistry:
    return parse_registry(json.loads(path.read_text(encoding="utf-8")))
