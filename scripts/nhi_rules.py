"""Effective dates of NHI drug reimbursement rules, read from the rule chapter PDFs themselves (G12 #167).

python scripts/nhi_rules.py [--write]

A regulatory row names its rule as nhiClause, e.g. "9.69 1.(11)" (item 1, sub-item (11) of chapter 9.69) or "9.134"
(the whole chapter), and its sources link the chapter PDF it was checked against (DurgFileName=9.69._20261001.pdf).
Every item of a rule ends with the dates it was amended, in ROC form: (113/6/1、114/6/1). The latest date anywhere in
the named item, its sub-items included, is when the rule as it stands took effect; that is nhiEffective.

Without --write the rows are only checked against the PDFs; with it, nhiEffective is set in data/papers.json. A clause
that cannot be found, or that carries no date, is an error: nothing is guessed.
"""

import argparse
import io
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

DATA = Path(__file__).resolve().parent.parent / "data" / "papers.json"
CHAPTER_PDF = re.compile(r"DurgFileName=(?P<chapter>\d+(?:\.\d+)*)\._(?P<version>\d{8})\.pdf")
CLAUSE = re.compile(r"^(?P<chapter>\d+(?:\.\d+)+)(?: (?P<item>\d{1,2})\.(?:\((?P<sub>\d{1,2})\))?)?$")
ITEM = re.compile(r"^\s*(\d{1,2})\.(?!\d)")  # "1." starts an item; "9.69." (the chapter heading) does not
SUB = re.compile(r"^\s*\((\d{1,2})\)")  # "(11)" starts a sub-item; "(114/6/1" does not
ROC_DATE = r"\d{2,3}/\d{1,2}/\d{1,2}"
DATES = re.compile(rf"[(（]\s*({ROC_DATE}(?:\s*[、,，]\s*{ROC_DATE})*)\s*[)）]")


class RuleError(ValueError):
    pass


def pdf_text(pdf: bytes) -> str:
    try:
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    except PyPdfError as error:  # a challenge page or a truncated download, not a rule
        raise RuleError(f"not a readable PDF: {error}") from error


def _span(lines: list[str], start: int, end: int, marker: re.Pattern[str], number: str) -> tuple[int, int]:
    """Lines [start, end) narrowed to the item numbered `number`, up to the next item of the same level."""
    begin = next((i for i in range(start, end) if (m := marker.match(lines[i])) and m[1] == number), None)
    if begin is None:
        raise RuleError(f"item {number} not found")
    finish = next((i for i in range(begin + 1, end) if marker.match(lines[i])), end)
    return begin, finish


def _roc(text: str) -> date:
    year, month, day = (int(part) for part in text.split("/"))
    try:
        return date(year + 1911, month, day)
    except ValueError as error:
        raise RuleError(f"not a date: {text}") from error


def clause_dates(text: str, clause: str) -> list[date]:
    """Every amendment date in the named clause, oldest first. `text` is one chapter's PDF text."""
    match = CLAUSE.match(clause)
    if not match:
        raise RuleError(f"clause must look like '9.69 1.(11)', '9.53 1.' or '9.134': {clause!r}")
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if line.lstrip().startswith(match["chapter"] + ".")), None)
    if heading is None:
        raise RuleError(f"chapter {match['chapter']} is not in this text")
    start, end = heading, len(lines)
    if match["item"]:
        start, end = _span(lines, heading + 1, end, ITEM, match["item"])
        if match["sub"]:
            start, end = _span(lines, start + 1, end, SUB, match["sub"])
    # Dates may wrap across lines inside one parenthesis, so the clause is joined before matching.
    found = {_roc(d.strip()) for group in DATES.findall("".join(lines[start:end])) for d in re.split(r"[、,，]", group)}
    if not found:
        raise RuleError(f"no amendment date in {clause}")
    return sorted(found)


def chapter_source(row: dict) -> tuple[str, str] | None:
    """(chapter, PDF link) of the rule PDF a row was checked against."""
    for source in row.get("sources", []):
        if match := CHAPTER_PDF.search(source):
            return match["chapter"], source
    return None


def regulatory_rows(data: dict) -> list[dict]:
    return [row for topic in data.values() for card in (topic.get("standard_of_care") or {}).get("cards", [])
            for row in card.get("regulatory", [])]  # fmt: skip


def effective(row: dict, get) -> date:
    """The row's nhiEffective according to the chapter PDF its sources link."""
    source = chapter_source(row)
    clause = row["nhiClause"]
    if source is None or clause.split()[0] != source[0]:
        raise RuleError(f"nhiClause {clause} does not match a rule PDF in sources")
    return clause_dates(pdf_text(get(source[1])), clause)[-1]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="set nhiEffective in data/papers.json")
    args = parser.parse_args(argv)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    failed = 0
    for row in regulatory_rows(data):
        if "nhiClause" not in row:
            continue
        try:
            found = effective(row, fetch).isoformat()
        except (RuleError, OSError) as error:
            print(f"ERROR {row['regimen']}: {error}", file=sys.stderr)
            failed += 1
            continue
        state = "ok" if row.get("nhiEffective") == found else f"was {row.get('nhiEffective')}"
        print(f"{row['nhiClause']:<14} {found}  {row['regimen']}  ({state})")
        if args.write:
            row["nhiEffective"] = found
    if args.write and not failed:
        DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
