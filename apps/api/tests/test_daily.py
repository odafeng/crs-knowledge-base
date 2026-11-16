"""The daily pick's rules without a database (G2 #113)."""

import re
from datetime import date

from guthub_api.daily import Candidate, choose, pick_text

DAY = date(2026, 11, 17)


def candidate(kind: str, ident: str, *, reviewed: bool = True, conclusion: str = "HR 0.62，延長存活") -> Candidate:
    return Candidate(
        kind=kind,  # pyright: ignore[reportArgumentType]
        ident=ident,
        title=f"{ident} 標題",
        conclusion=conclusion,
        path=f"/{kind}/{ident}/",
        date=DAY,
        unreviewed=not reviewed,
    )


def test_coverage_changes_come_before_news_and_news_before_papers() -> None:
    papers = [candidate("paper", "p1")]
    news = [candidate("news", "n1")]
    coverage = [candidate("regulatory", "r1")]
    assert choose(papers + news + coverage) == coverage[0]
    assert choose(papers + news) == news[0]
    assert choose(papers) == papers[0]


def test_reviewed_entries_come_before_unreviewed_ones_of_the_same_kind() -> None:
    auto, accepted = candidate("news", "a", reviewed=False), candidate("news", "b")
    assert choose([auto, accepted]) == accepted
    # Kind still wins over review: an unreviewed story beats a reviewed paper, and says it is unreviewed.
    assert choose([candidate("paper", "p"), auto]) == auto


def test_no_new_content_means_no_pick() -> None:
    assert choose([]) is None


def test_text_has_title_conclusion_link_and_date_only() -> None:
    text = pick_text(candidate("news", "niche2"), "https://guthub.tw")
    assert text == "niche2 標題\nHR 0.62，延長存活\nhttps://guthub.tw/news/niche2/\n2026-11-17"
    unreviewed = pick_text(candidate("news", "x", reviewed=False), "https://guthub.tw")
    assert unreviewed.splitlines()[0] == "【AI 未審】x 標題"


def test_every_number_comes_from_the_entry() -> None:
    entry = candidate("paper", "keynote", conclusion="5 年 OS 58.7% vs 47.1%（HR 0.71）")
    text = pick_text(entry, "https://guthub.tw")
    source = " ".join([entry.title, entry.conclusion, entry.path, entry.date.isoformat(), "https://guthub.tw"])
    assert set(re.findall(r"\d+(?:\.\d+)?", text)) <= set(re.findall(r"\d+(?:\.\d+)?", source))
