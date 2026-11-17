"""NHI rule effective dates (G12 #167): clauses cut from text extracted from the real chapter PDFs."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import nhi_rules
import regulatory_watch as watch

FIXTURES = Path(__file__).parent / "fixtures" / "nhi"
CETUXIMAB = (FIXTURES / "9.27.txt").read_text(encoding="utf-8")
PANITUMUMAB = (FIXTURES / "9.53.txt").read_text(encoding="utf-8")
ICI = (FIXTURES / "9.69-excerpt.txt").read_text(encoding="utf-8")
PDF = "https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName={}"


def test_a_sub_item_is_cut_at_the_next_item_and_its_dates_read() -> None:
    # (11) ends at "2.", whose heading dates (114/6/1 … 115/10/1) belong to item 2, not to (11).
    assert nhi_rules.clause_dates(ICI, "9.69 1.(11)") == [date(2025, 6, 1)]


def test_sub_items_count_and_dates_wrapping_across_lines_are_read() -> None:
    # 1.(1) of cetuximab: its own dates, then Ⅱ. and Ⅳ. below it; (2) starts a new sub-item.
    dates = nhi_rules.clause_dates(CETUXIMAB, "9.27 1.(1)")
    assert dates[0] == date(2012, 12, 1) and dates[-1] == date(2026, 2, 1)
    assert date(2026, 5, 1) not in dates  # 115/5/1 is (2), encorafenib combination
    assert nhi_rules.clause_dates(CETUXIMAB, "9.27 1.(2)") == [date(2026, 5, 1)]


def test_a_whole_item_and_a_whole_chapter() -> None:
    assert nhi_rules.clause_dates(PANITUMUMAB, "9.53 1.")[-1] == date(2026, 2, 1)
    whole = nhi_rules.clause_dates(PANITUMUMAB, "9.53")
    assert whole[0] == date(2009, 8, 1) and whole[-1] == date(2026, 2, 1)


@pytest.mark.parametrize(
    ("text", "clause", "problem"),
    [
        (ICI, "9.69 1.(12)", "item 12 not found"),
        (ICI, "9.69 3.", "item 3 not found"),
        (ICI, "9.27 1.", "chapter 9.27 is not in this text"),
        (ICI, "9.69 第一項", "clause must look like"),
        ("9.99.Some drug\n1.未標日期的條文。", "9.99 1.", "no amendment date"),
        ("9.99.Some drug\n1.條文。(115/13/1)", "9.99 1.", "not a date"),
    ],
)
def test_nothing_is_guessed(text: str, clause: str, problem: str) -> None:
    with pytest.raises(nhi_rules.RuleError, match=problem):
        nhi_rules.clause_dates(text, clause)


def test_a_row_must_name_a_clause_of_the_pdf_it_cites() -> None:
    row = {"regimen": "x", "nhiClause": "9.27 1.(1)", "sources": [PDF.format("9.53._20260201.pdf")]}
    with pytest.raises(nhi_rules.RuleError, match="does not match"):
        nhi_rules.effective(row, lambda _url: b"")


def test_a_page_that_is_not_a_pdf_is_an_error() -> None:
    with pytest.raises(nhi_rules.RuleError, match="not a readable PDF"):
        nhi_rules.pdf_text(b"<html>Just a moment...</html>")


def card(regimen: str, clause: str, effective: str) -> tuple[str, dict]:
    return (
        "mCRC-RAS-wt",
        {
            "regimen": regimen,
            "nhiClause": clause,
            "nhiEffective": effective,
            "sources": [PDF.format("9.27._20260501.pdf")],
            "checkedAt": "2026-11-17",
        },
    )


NEWER = {"9.27.": ("20261101", PDF.format("9.27._20261101.pdf"))}


def test_a_new_version_reports_each_clause_date() -> None:
    cards = [card("Cetuximab + FOLFIRI", "9.27 1.(1)", "2025-02-01")]
    [finding] = watch.nhi_findings(cards, NEWER, lambda _link: CETUXIMAB)
    assert "9.27 1.(1) 新版最新日期 2026-02-01（卡片記錄 2025-02-01）" in finding.body
    assert "可能與大腸直腸癌無關" not in finding.body


def test_a_new_version_that_leaves_the_clauses_alone_says_so() -> None:
    cards = [card("Cetuximab + FOLFIRI", "9.27 1.(1)", "2026-02-01")]
    [finding] = watch.nhi_findings(cards, NEWER, lambda _link: CETUXIMAB)
    assert "可能與大腸直腸癌無關" in finding.body


def test_an_unreadable_new_version_still_opens_the_finding() -> None:
    def broken(_link: str) -> str:
        raise nhi_rules.RuleError("not a readable PDF: EOF")

    [finding] = watch.nhi_findings([card("Cetuximab + FOLFIRI", "9.27 1.(1)", "2026-02-01")], NEWER, broken)
    assert "無法讀取新版 PDF" in finding.body and "有新版 20261101" in finding.title
