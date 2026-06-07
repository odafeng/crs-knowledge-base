"""Validate data integrity of the CRS Knowledge Base.

Checks:
1. No duplicate paper IDs across all *_PAPERS arrays
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
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = PROJECT_ROOT / "index.html"

KNOWN_STUDY_TYPES = {
    "Phase 3 RCT", "Phase 3 RCT (updated)", "Phase 3 RCT (final)",
    "Phase 3 RCT (final OS)", "Phase 3 (Cohort 3)",
    "Phase 2 RCT", "Phase 2", "Phase 2 (exploratory)",
    "Phase 2a (basket)",
    "Phase 1-2", "Phase 1-2 (expanded)",
    "Phase 1", "Phase 1b",
    "Biomarker (exploratory)", "Post-hoc analysis",
    "Meta-analysis", "Pooled analysis",
}

REQUIRED_FIELDS = ["id", "year", "journal", "studyType", "regimen", "endpoint", "result", "bottomLine"]


def _extract_papers() -> dict[str, list[dict]]:
    """Extract paper objects from index.html using regex + JSON-ish parsing."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    arrays = {}

    for match in re.finditer(r"const (\w+_PAPERS)\s*=\s*\[(.*?)\];", html, re.DOTALL):
        var_name = match.group(1)
        raw = match.group(2)

        # Convert JS objects to JSON-ish (handle unquoted keys, single quotes)
        papers = []
        for obj_match in re.finditer(r"\{([^}]+)\}", raw):
            obj_text = obj_match.group(1)

            # Match both JS-style (id:'...') and JSON-style ("id": "...")
            def _field(name, text):
                return re.search(rf'["\']?{name}["\']?\s*:\s*["\']([^"\']+)["\']', text)

            # Skip nested objects (relations, etc.) — they don't have 'id' + 'year'
            id_match = _field("id", obj_text)
            if not id_match:
                continue
            doi_match = re.search(r'["\']?doi["\']?\s*:\s*["\']([^"\']*)["\']', obj_text)
            file_match = _field("file", obj_text)
            year_match = re.search(r'["\']?year["\']?\s*:\s*(\d+)', obj_text)
            journal_match = _field("journal", obj_text)
            study_match = _field("studyType", obj_text)
            regimen_match = _field("regimen", obj_text)
            endpoint_match = _field("endpoint", obj_text)
            result_match = _field("result", obj_text)
            bottom_match = _field("bottomLine", obj_text)

            # Extract relation targetIds
            relations = []
            for rel_match in re.finditer(r'["\']?targetId["\']?\s*:\s*["\']([^"\']+)["\']', obj_text):
                relations.append(rel_match.group(1))

            papers.append({
                "id": id_match.group(1) if id_match else "",
                "doi": doi_match.group(1) if doi_match else "",
                "file": file_match.group(1) if file_match else None,
                "year": int(year_match.group(1)) if year_match else 0,
                "journal": journal_match.group(1) if journal_match else "",
                "studyType": study_match.group(1) if study_match else "",
                "regimen": regimen_match.group(1) if regimen_match else "",
                "endpoint": endpoint_match.group(1) if endpoint_match else "",
                "result": result_match.group(1) if result_match else "",
                "bottomLine": bottom_match.group(1) if bottom_match else "",
                "relation_targets": relations,
                "_array": var_name,
            })

        arrays[var_name] = papers

    return arrays


def validate() -> list[str]:
    """Run all validation checks. Returns list of error messages."""
    errors = []
    arrays = _extract_papers()

    if not arrays:
        errors.append("No paper arrays found in index.html")
        return errors

    # Collect all IDs and DOIs
    all_ids: dict[str, str] = {}  # id → array name
    all_dois: dict[str, str] = {}  # doi → array name
    all_papers = []

    for var_name, papers in arrays.items():
        for p in papers:
            all_papers.append(p)

            # Check duplicate IDs
            pid = p["id"]
            if not pid:
                errors.append(f"[{var_name}] Paper with empty id")
            elif pid in all_ids:
                errors.append(f"[{var_name}] Duplicate id '{pid}' (also in {all_ids[pid]})")
            else:
                all_ids[pid] = var_name

            # Check duplicate DOIs
            doi = p["doi"]
            if doi:
                if doi in all_dois:
                    errors.append(f"[{var_name}] Duplicate DOI '{doi}' (also in {all_dois[doi]})")
                else:
                    all_dois[doi] = var_name

    # Check relation targets exist
    for p in all_papers:
        for target in p["relation_targets"]:
            if target not in all_ids:
                errors.append(f"[{p['_array']}] Paper '{p['id']}' has relation to unknown target '{target}'")

    # Check local file references exist
    for p in all_papers:
        if p["file"] and not p["file"].startswith("http"):
            file_path = PROJECT_ROOT / p["file"]
            if not file_path.exists():
                errors.append(f"[{p['_array']}] Paper '{p['id']}' references missing file: {p['file']}")

    # Check required fields
    for p in all_papers:
        for field in REQUIRED_FIELDS:
            if not p.get(field):
                errors.append(f"[{p['_array']}] Paper '{p['id']}' has empty required field: {field}")

    # Check studyType values
    for p in all_papers:
        st = p["studyType"]
        if st and st not in KNOWN_STUDY_TYPES:
            errors.append(f"[{p['_array']}] Paper '{p['id']}' has unknown studyType: '{st}'")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate CRS Knowledge Base data integrity")
    parser.add_argument("--ci", action="store_true", help="Exit 1 on any error")
    args = parser.parse_args()

    print("[Validate] Checking data integrity...")
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
