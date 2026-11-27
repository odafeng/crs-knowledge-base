"""Dry-run manifest generator, transactional backfill, and verifier for T2 #283 (ADR-0030).

Usage:
  python scripts/taxonomy_backfill.py dry-run --from-json --out manifest.json
  python scripts/taxonomy_backfill.py dry-run --database-url URL --out manifest.json
  python scripts/taxonomy_backfill.py apply   --database-url URL --manifest approved.json [--dry-run]
  python scripts/taxonomy_backfill.py verify  --database-url URL

Follows ADR-0030 Expand -> Backfill -> Verify -> Switch -> Contract and ADR-0021 Single Content Writer:
- Never mutates app.papers, app.topics, app.news, app.topic_subscriptions, or app.forum_posts.
- Acquires pg_advisory_xact_lock(hashtext('guthub-content-writer')) during apply.
- Fails closed if any manifest entry still needs_review without reviewed=true or has no primary domain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from taxonomy_registry import TaxonomyError, TaxonomyRegistry, load_registry

ROOT = Path(__file__).resolve().parent.parent
LOCK_SQL = "select pg_advisory_xact_lock(hashtext('guthub-content-writer'))"
DATABASE_ENV = "GUTHUB_CONTENT_DATABASE_URL"

_AI_PATTERNS = re.compile(
    r"\b(deep learning|machine learning|artificial intelligence|neural network|radiomics|pelvimetry|"
    r"computer vision|phase recognition|autonomous surgery|surgical ai|ai-assisted)\b",
    re.IGNORECASE,
)
_PERIO_PATTERNS = re.compile(
    r"\b(anastomotic leak(?:age)?|eras|prehabilitation|sarcopenia|immunonutrition|stoma)\b|吻合口滲漏|造口|營養",
    re.IGNORECASE,
)
_LATER_LINE_PATTERNS = re.compile(
    r"\b(regorafenib|fruquintinib|trifluridine|tas-102|ftd[-/]tpi|zanzalintinib|refractory mcrc|"
    r"3l\+|third-line|salvage|later-line)\b|後線|難治",
    re.IGNORECASE,
)
_TNT_PATTERNS = re.compile(
    r"\b(total neoadjuvant|tnt|watch-and-wait|nonoperative|organ preservation|larc)\b|直腸癌|器官保留",
    re.IGNORECASE,
)
_CTDNA_PATTERNS = re.compile(
    r"\b(ctdna|circulating tumor dna|adjuvant chemotherapy)\b|輔助化療",
    re.IGNORECASE,
)


class BackfillError(RuntimeError):
    """Raised when a manifest is incomplete, unreviewed, invalid, or mismatched with the DB."""


def _paper_text(paper: dict[str, Any]) -> str:
    return " ".join(
        str(paper.get(field) or "")
        for field in ("id", "regimen", "endpoint", "result", "bottom_line", "bottomLine", "title")
    )


def classify_paper(paper: dict[str, Any], registry: TaxonomyRegistry) -> dict[str, Any]:
    """Produce a deterministic proposed taxonomy mapping entry for one paper."""
    paper_id = str(paper["id"])
    legacy_key = str(paper.get("topic_key") or paper.get("topic") or "")
    doi = paper.get("doi") or None
    withdrawn = bool(paper.get("withdrawn") or paper.get("withdrawn_at"))
    text = _paper_text(paper)

    primary: str | None = None
    secondaries: list[str] = []
    subtopic: str | None = None
    confidence = "ambiguous"
    needs_review = True
    reason = "unknown legacy_topic_key"

    if legacy_key in registry.aliases:
        alias = registry.aliases[legacy_key]
        if alias.policy == "direct":
            primary = alias.domain
            subtopic = alias.subtopic
            confidence = "high"
            needs_review = False
            reason = f"direct legacy alias ({legacy_key} -> {primary}/{subtopic})"
        elif alias.policy == "default_candidate":
            primary = alias.domain
            subtopic = alias.subtopic
            if _AI_PATTERNS.search(text):
                secondaries.append("surgical-intelligence")
                confidence = "medium"
                needs_review = True
                reason = "robotic-surgery with AI/surgical-intelligence signal; review primary vs secondary"
            else:
                confidence = "high"
                needs_review = False
                reason = f"default surgical candidate ({legacy_key} -> {primary})"
            if _PERIO_PATTERNS.search(text) and "perioperative-care-nutrition" not in secondaries:
                secondaries.append("perioperative-care-nutrition")
        elif alias.policy == "manual_review_required":
            # Every generic-CRS paper requires explicit maintainer sign-off (ADR-0030).
            needs_review = True
            if _LATER_LINE_PATTERNS.search(text):
                primary = "colorectal-oncology"
                subtopic = "mcrc-later-line"
                confidence = "high"
                reason = "generic-CRS refractory/later-line mCRC trial; requires maintainer sign-off"
            elif _TNT_PATTERNS.search(text):
                primary = "colorectal-oncology"
                subtopic = "colorectal-tnt-organ-preservation"
                confidence = "high"
                reason = "generic-CRS rectal cancer TNT/organ-preservation study; requires maintainer sign-off"
            elif _CTDNA_PATTERNS.search(text):
                primary = "colorectal-oncology"
                subtopic = "colorectal-ctdna-adjuvant"
                confidence = "high"
                reason = "generic-CRS ctDNA/adjuvant oncology study; requires maintainer sign-off"
            else:
                primary = None
                subtopic = None
                confidence = "ambiguous"
                reason = "generic-CRS ambiguous entry; manual domain classification required"
    elif legacy_key in registry.active_domain_slugs:
        primary = legacy_key
        subtopic = None
        confidence = "high"
        needs_review = False
        reason = f"already assigned to active domain slug ({legacy_key})"

    return {
        "paper_id": paper_id,
        "doi": doi,
        "legacy_topic_key": legacy_key,
        "withdrawn": withdrawn,
        "proposed_primary_domain": primary,
        "proposed_secondary_domains": secondaries,
        "proposed_subtopic_id": subtopic,
        "confidence": confidence,
        "needs_review": needs_review,
        "reviewed": False,
        "reason": reason,
    }


def build_manifest(papers: list[dict[str, Any]], registry: TaxonomyRegistry) -> dict[str, Any]:
    """Build a deterministic dry-run mapping manifest with summary counts and content digest."""
    entries = [classify_paper(paper, registry) for paper in sorted(papers, key=lambda p: str(p["id"]))]
    by_domain: dict[str, int] = {}
    for entry in entries:
        key = entry["proposed_primary_domain"] or "UNASSIGNED"
        by_domain[key] = by_domain.get(key, 0) + 1
    canonical = json.dumps(entries, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "taxonomy_version": registry.version,
        "digest_sha256": hashlib.sha256(canonical).hexdigest(),
        "summary": {
            "total": len(entries),
            "active": sum(1 for e in entries if not e["withdrawn"]),
            "withdrawn": sum(1 for e in entries if e["withdrawn"]),
            "needs_review": sum(1 for e in entries if e["needs_review"]),
            "ambiguous": sum(1 for e in entries if e["confidence"] == "ambiguous"),
            "by_proposed_primary_domain": dict(sorted(by_domain.items())),
        },
        "entries": entries,
    }


def load_papers_from_json(path: Path = ROOT / "data" / "papers.json") -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    papers: list[dict[str, Any]] = []
    for topic_key, block in raw.items():
        for paper in block.get("papers", []):
            papers.append({**paper, "topic_key": topic_key, "withdrawn": False})
    return papers


def load_papers_from_db(conn: Any) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        return list(
            cur.execute(
                "select id, doi, topic_key, year, journal, regimen, endpoint, result, bottom_line, withdrawn_at"
                " from app.papers order by id"
            ).fetchall()
        )


def validate_manifest_for_apply(manifest_doc: dict[str, Any], registry: TaxonomyRegistry) -> list[dict[str, Any]]:
    """Fail closed unless every entry is valid, reviewed when required, and has a primary domain."""
    try:
        registry.require_version(str(manifest_doc.get("taxonomy_version", "")))
    except TaxonomyError as exc:
        raise BackfillError(str(exc)) from exc

    entries = manifest_doc.get("entries")
    if not isinstance(entries, list):
        raise BackfillError("manifest missing 'entries' list")

    errors: list[str] = []
    seen_ids: set[str] = set()
    for entry in entries:
        pid = str(entry.get("paper_id") or "")
        if not pid:
            errors.append("entry missing paper_id")
            continue
        if pid in seen_ids:
            errors.append(f"duplicate paper_id in manifest: {pid}")
            continue
        seen_ids.add(pid)
        if entry.get("needs_review") and not entry.get("reviewed"):
            errors.append(f"{pid}: needs_review is true but reviewed is not true")
            continue
        primary = entry.get("proposed_primary_domain")
        if not primary:
            errors.append(f"{pid}: missing proposed_primary_domain")
            continue
        secondaries = entry.get("proposed_secondary_domains") or []
        subtopic = entry.get("proposed_subtopic_id")
        subtopics = [subtopic] if subtopic else []
        try:
            registry.validate_assignment(
                primary_domain=primary,
                secondary_domains=secondaries,
                subtopics=subtopics,
                taxonomy_version=manifest_doc["taxonomy_version"],
            )
        except TaxonomyError as exc:
            errors.append(f"{pid}: {exc}")

    if errors:
        raise BackfillError("manifest failed pre-apply validation:\n- " + "\n- ".join(errors))
    return entries


def apply_manifest(
    conn: Any,
    manifest_doc: dict[str, Any],
    registry: TaxonomyRegistry,
    *,
    dry_run: bool = False,
    assigned_by: str = "taxonomy-backfill",
) -> dict[str, int]:
    """Apply an approved manifest to app.paper_domains inside one locked transaction (idempotent)."""
    from psycopg import Rollback

    entries = validate_manifest_for_apply(manifest_doc, registry)
    version = str(manifest_doc["taxonomy_version"])
    stats = {"inserted": 0, "updated": 0, "removed": 0, "unchanged": 0}

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(LOCK_SQL)
        existing_paper_ids = {row[0] for row in cur.execute("select id from app.papers").fetchall()}
        missing = [e["paper_id"] for e in entries if e["paper_id"] not in existing_paper_ids]
        if missing:
            raise BackfillError(f"manifest references papers absent from app.papers: {', '.join(missing[:10])}")

        for entry in entries:
            pid = entry["paper_id"]
            primary = entry["proposed_primary_domain"]
            subtopic = entry.get("proposed_subtopic_id")
            secondaries = list(entry.get("proposed_secondary_domains") or [])

            desired: dict[str, tuple[bool, str | None, str]] = {primary: (True, subtopic, version)}
            for sec in secondaries:
                desired[sec] = (False, None, version)

            current_rows = cur.execute(
                "select domain_slug, is_primary, subtopic_id, taxonomy_version"
                " from app.paper_domains where paper_id = %s",
                (pid,),
            ).fetchall()
            current = {row[0]: (bool(row[1]), row[2], row[3]) for row in current_rows}

            if current == desired:
                stats["unchanged"] += len(desired)
                continue

            obsolete = [slug for slug in current if slug not in desired]
            if obsolete:
                cur.execute(
                    "delete from app.paper_domains where paper_id = %s and domain_slug = any(%s)",
                    (pid, obsolete),
                )
                stats["removed"] += cur.rowcount

            # Clear any existing primary flag on another domain before setting the new primary
            # so paper_domains_one_primary never collides during primary reassignment.
            cur.execute(
                "update app.paper_domains set is_primary = false"
                " where paper_id = %s and is_primary = true and domain_slug <> %s",
                (pid, primary),
            )

            for slug, (is_primary, sub_id, ver) in desired.items():
                if slug not in current:
                    cur.execute(
                        "insert into app.paper_domains"
                        " (paper_id, domain_slug, is_primary, subtopic_id, taxonomy_version, assigned_by)"
                        " values (%s, %s, %s, %s, %s, %s)",
                        (pid, slug, is_primary, sub_id, ver, assigned_by),
                    )
                    stats["inserted"] += 1
                elif current[slug] != (is_primary, sub_id, ver):
                    cur.execute(
                        "update app.paper_domains"
                        " set is_primary = %s, subtopic_id = %s, taxonomy_version = %s,"
                        " assigned_by = %s, assigned_at = now()"
                        " where paper_id = %s and domain_slug = %s",
                        (is_primary, sub_id, ver, assigned_by, pid, slug),
                    )
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1

        if dry_run:
            raise Rollback()

    return stats


def verify_backfill(conn: Any, registry: TaxonomyRegistry) -> dict[str, Any]:
    """Verify every active public paper has exactly one primary domain and valid registry version."""
    active_ids = [row[0] for row in conn.execute("select id from app.public_papers order by id").fetchall()]
    primaries = {
        row[0]
        for row in conn.execute(
            "select pd.paper_id from app.paper_domains pd"
            " join app.public_papers p on p.id = pd.paper_id where pd.is_primary = true"
        ).fetchall()
    }
    missing_primary = [pid for pid in active_ids if pid not in primaries]
    invalid_row = conn.execute(
        "select count(*) from app.paper_domains where taxonomy_version <> %s",
        (registry.version,),
    ).fetchone()
    invalid_versions = int(invalid_row[0]) if invalid_row else 0
    counts = dict(
        conn.execute(
            "select pd.domain_slug, count(distinct pd.paper_id)::int from app.paper_domains pd"
            " join app.public_papers p on p.id = pd.paper_id group by pd.domain_slug order by pd.domain_slug"
        ).fetchall()
    )
    return {
        "ok": len(missing_primary) == 0 and invalid_versions == 0,
        "taxonomy_version": registry.version,
        "active_papers": len(active_ids),
        "missing_primary": missing_primary,
        "invalid_versions": invalid_versions,
        "domain_counts": counts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_dry = sub.add_parser("dry-run", help="generate a read-only taxonomy mapping manifest")
    p_dry.add_argument("--database-url", default=os.environ.get(DATABASE_ENV))
    p_dry.add_argument("--from-json", action="store_true", help="read local data/papers.json instead of DB")
    p_dry.add_argument("--out", type=Path, help="write manifest JSON to path (default: stdout)")

    p_apply = sub.add_parser("apply", help="apply an approved manifest to app.paper_domains")
    p_apply.add_argument("--database-url", default=os.environ.get(DATABASE_ENV))
    p_apply.add_argument("--manifest", type=Path, required=True)
    p_apply.add_argument("--dry-run", action="store_true", help="run inside a transaction and roll back")

    p_verify = sub.add_parser("verify", help="verify backfill integrity in PostgreSQL")
    p_verify.add_argument("--database-url", default=os.environ.get(DATABASE_ENV))

    args = parser.parse_args(argv)
    registry = load_registry()

    if args.command == "dry-run":
        if args.from_json:
            papers = load_papers_from_json()
        else:
            if not args.database_url:
                parser.error("--database-url (or --from-json) is required")
            import psycopg

            with psycopg.connect(args.database_url) as conn:
                papers = load_papers_from_db(conn)
        manifest_doc = build_manifest(papers, registry)
        rendered = json.dumps(manifest_doc, indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0

    if not args.database_url:
        parser.error(f"--database-url (or {DATABASE_ENV}) is required")
    import psycopg

    with psycopg.connect(args.database_url) as conn:
        if args.command == "apply":
            manifest_doc = json.loads(args.manifest.read_text(encoding="utf-8"))
            try:
                stats = apply_manifest(conn, manifest_doc, registry, dry_run=args.dry_run)
            except BackfillError as exc:
                print(str(exc), file=sys.stderr)
                return 1
            print(json.dumps({"dry_run": args.dry_run, **stats}, indent=2))
            return 0
        report = verify_backfill(conn, registry)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
