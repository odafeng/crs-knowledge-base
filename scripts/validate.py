"""Validate data integrity of the Seminar Hegemon knowledge base.

Reads from data/papers.json (single source of truth).
No regex parsing of index.html — just json.load.

Checks:
1. No duplicate paper IDs across all topics
2. All relation targetIds reference existing paper IDs
3. All local file references (docs/*.html) actually exist
4. Required fields are non-empty
5. studyType values match known badges
6. No duplicate DOIs
7. Related commentary entries are complete, typed, and not duplicated
8. Bot-published entries (``review`` field) carry a known status and date, and no raw HTML
9. Every paper says how its numbers were checked (``source``) and when (``reviewedAt``)

Usage:
  python scripts/validate.py        # run all checks
  python scripts/validate.py --ci   # exit 1 on any error (for CI)
"""

import argparse
import json
import re
import sys
from pathlib import Path

from commentary import COMMENTARY_TYPES

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PAPERS_JSON = PROJECT_ROOT / "data" / "papers.json"

KNOWN_STUDY_TYPES = {
    "Phase 3 RCT",
    "Phase 3 RCT (updated)",
    "Phase 3 RCT (final)",
    "Phase 3 RCT (final OS)",
    "Phase 3 (Cohort 3)",
    "Phase 2 RCT",
    "Phase 2",
    "Phase 2 (updated)",
    "Phase 2 (exploratory)",
    "Phase 2a (basket)",
    "Phase 1-2",
    "Phase 1-2 (expanded)",
    "Phase 1",
    "Phase 1b",
    "Biomarker (exploratory)",
    "Post-hoc analysis",
    "Meta-analysis",
    "Pooled analysis",
    "Retrospective cohort",
    "Guideline",
}

REQUIRED_FIELDS = ["id", "year", "journal", "studyType", "regimen", "endpoint", "result", "bottomLine"]
COMMENTARY_FIELDS = ["title", "journal", "type", "summary", "addedAt"]
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}$")
# "auto": published by the gate without a human; "accepted": a reviewer approved it (ADR-0013)
REVIEW_STATUSES = ("auto", "accepted")
# How the numbers were checked: full text, PubMed abstract only, secondary coverage (news,
# conference reports), or hand-curated before this field existed (level not recorded).
SOURCES = ("fulltext", "abstract", "secondary", "curated")


def _validate_review(label: str, item: dict) -> list[str]:
    review = item.get("review")
    if review is None:
        return []
    errors = []
    if review.get("status") not in REVIEW_STATUSES:
        errors.append(f"{label} has unknown review status: {review.get('status')!r}")
    if not _DATE.match(str(review.get("publishedAt", ""))):
        errors.append(f"{label} review.publishedAt must be YYYY-MM-DD")
    # Model-written text is escaped on publish; raw markup here means it bypassed that.
    for key, value in item.items():
        if isinstance(value, str) and "<" in value:
            errors.append(f"{label} field {key} contains raw HTML")
    return errors


def _validate_commentary(topic: str, pid: str, items: list[dict], seen: dict[str, str]) -> list[str]:
    errors = []
    for c in items:
        key = c.get("doi") or c.get("pmid")
        label = f"[{topic}] Paper '{pid}' commentary '{key or c.get('title', '?')}'"
        if not key:
            errors.append(f"{label} needs a doi or pmid")
        for field in COMMENTARY_FIELDS:
            if not c.get(field):
                errors.append(f"{label} has empty field: {field}")
        if c.get("type") and c["type"] not in COMMENTARY_TYPES:
            errors.append(f"{label} has unknown type: '{c['type']}'")
        for flag in ("critique", "newData"):
            if not isinstance(c.get(flag), bool):
                errors.append(f"{label} needs boolean {flag}")
        if c.get("addedAt") and not _DATE.match(c["addedAt"]):
            errors.append(f"{label} addedAt must be YYYY-MM-DD")
        errors += _validate_review(label, c)
        if key:
            if key in seen:
                errors.append(f"{label} duplicates {seen[key]}")
            seen[key] = f"commentary on '{pid}'"
    return errors


def validate() -> list[str]:
    """Run all validation checks on data/papers.json. Returns list of error messages."""
    if not PAPERS_JSON.exists():
        return [f"data/papers.json not found at {PAPERS_JSON}"]
    return validate_data(json.loads(PAPERS_JSON.read_text()))


def validate_data(data: dict, root: Path = PROJECT_ROOT, pending_files: frozenset[str] = frozenset()) -> list[str]:
    """Run all validation checks on parsed papers.json data.

    ``root`` is where ``file`` references resolve; ``pending_files`` are about to be
    written by the caller and count as present.
    """
    errors = []
    all_ids: dict[str, str] = {}  # id → topic
    all_dois: dict[str, str] = {}  # doi → topic

    for topic, topic_data in data.items():
        papers = topic_data.get("papers", [])

        for p in papers:
            pid = p.get("id", "")
            if not pid:
                errors.append(f"[{topic}] Paper with empty id")
                continue

            # Duplicate IDs
            if pid in all_ids:
                errors.append(f"[{topic}] Duplicate id '{pid}' (also in {all_ids[pid]})")
            else:
                all_ids[pid] = topic

            # Duplicate DOIs
            doi = p.get("doi") or ""
            if doi:
                if doi in all_dois:
                    errors.append(f"[{topic}] Duplicate DOI '{doi}' (also in {all_dois[doi]})")
                else:
                    all_dois[doi] = topic

            # Required fields
            for field in REQUIRED_FIELDS:
                val = p.get(field)
                if val is None or val == "":
                    errors.append(f"[{topic}] Paper '{pid}' has empty required field: {field}")

            errors += _validate_review(f"[{topic}] Paper '{pid}'", p)
            if p.get("source") not in SOURCES:
                errors.append(f"[{topic}] Paper '{pid}' has unknown source: {p.get('source')!r}")
            if not _DATE.match(str(p.get("reviewedAt", ""))):
                errors.append(f"[{topic}] Paper '{pid}' reviewedAt must be YYYY-MM-DD")

            # studyType
            st = p.get("studyType", "")
            if st and st not in KNOWN_STUDY_TYPES:
                errors.append(f"[{topic}] Paper '{pid}' has unknown studyType: '{st}'")

            # Local file references
            file_ref = p.get("file")
            if file_ref and not file_ref.startswith("http") and file_ref not in pending_files:
                file_path = root / file_ref
                if not file_path.exists():
                    errors.append(f"[{topic}] Paper '{pid}' references missing file: {file_ref}")

            # Relation targets
            for rel in p.get("relations", []):
                target = rel.get("targetId", "")
                if target and target not in all_ids:
                    # Check if it's in a later topic (forward reference)
                    found = False
                    for _t2, t2_data in data.items():
                        for p2 in t2_data.get("papers", []):
                            if p2.get("id") == target:
                                found = True
                                break
                        if found:
                            break
                    if not found:
                        errors.append(f"[{topic}] Paper '{pid}' has relation to unknown target '{target}'")

    # Commentary keys must be unique and must not be a paper in the KB
    seen: dict[str, str] = {doi: f"paper in {t}" for doi, t in all_dois.items()}
    for topic, topic_data in data.items():
        for p in topic_data.get("papers", []):
            errors += _validate_commentary(topic, p.get("id", ""), p.get("commentary", []), seen)

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate Seminar Hegemon data integrity")
    parser.add_argument("--ci", action="store_true", help="Exit 1 on any error")
    args = parser.parse_args()

    print("[Validate] Checking data/papers.json integrity...")
    errors = validate()

    if errors:
        print(f"\n{len(errors)} error(s) found:\n")
        for e in errors:
            print(f"  ✗ {e}")
        if args.ci:
            sys.exit(1)
    else:
        print("  ✓ All checks passed")


if __name__ == "__main__":
    main()
