"""Validate data integrity of the CRS Knowledge Base.

Reads from data/papers.json (single source of truth).
No regex parsing of index.html — just json.load.

Checks:
1. No duplicate paper IDs across all topics
2. All relation targetIds reference existing paper IDs
3. All local file references (docs/*.html) actually exist
4. Required fields are non-empty
5. studyType values match known badges
6. No duplicate DOIs

Usage:
  python scripts/validate.py        # run all checks
  python scripts/validate.py --ci   # exit 1 on any error (for CI)
"""

import argparse
import json
import sys
from pathlib import Path

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
    "Editorial",
}

REQUIRED_FIELDS = ["id", "year", "journal", "studyType", "regimen", "endpoint", "result", "bottomLine"]


def validate() -> list[str]:
    """Run all validation checks. Returns list of error messages."""
    errors = []

    if not PAPERS_JSON.exists():
        errors.append(f"data/papers.json not found at {PAPERS_JSON}")
        return errors

    with open(PAPERS_JSON) as f:
        data = json.load(f)

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

            # studyType
            st = p.get("studyType", "")
            if st and st not in KNOWN_STUDY_TYPES:
                errors.append(f"[{topic}] Paper '{pid}' has unknown studyType: '{st}'")

            # Local file references
            file_ref = p.get("file")
            if file_ref and not file_ref.startswith("http"):
                file_path = PROJECT_ROOT / file_ref
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

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate CRS Knowledge Base data integrity")
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
