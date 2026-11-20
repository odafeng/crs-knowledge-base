"""The daily pick's rules without a database (G2 #113)."""

import re
from datetime import UTC, date, datetime

from guthub_api.conference import season_on
from guthub_api.daily import Candidate, choose, pick_text, ranked
from guthub_api.line import ROUNDUP, roundup
from guthub_api.maintenance import line_day

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


def test_the_morning_broadcast_covers_the_day_before() -> None:
    # Paper Watch publishes at 16:00, so the 07:00 message is the only one that can carry those papers (#114).
    assert line_day(datetime(2026, 11, 17, 23, 0, tzinfo=UTC)) == date(2026, 11, 17)  # 07:00 on the 18th in Taipei
    assert line_day(datetime(2026, 1, 1, 7, 0, tzinfo=UTC)) == date(2025, 12, 31)


SEASONS = {
    "ESMO": {"start": "09-05", "end": "11-05", "name": "ESMO Congress"},
    "SABCS": {"start": "12-15", "end": "01-10", "name": "Year-end"},
}


def test_conference_windows_include_both_ends_and_may_wrap_the_new_year() -> None:
    assert season_on(date(2026, 9, 5), SEASONS) == season_on(date(2026, 11, 5), SEASONS) == "ESMO Congress"
    assert season_on(date(2026, 11, 6), SEASONS) is None
    assert season_on(date(2026, 12, 31), SEASONS) == season_on(date(2027, 1, 10), SEASONS) == "Year-end"
    assert season_on(date(2027, 1, 11), SEASONS) is None


def test_the_shipped_windows_load() -> None:
    assert season_on(date(2026, 10, 20)) == "ESMO Congress"
    assert season_on(date(2026, 3, 15)) is None


def test_the_conference_roundup_lists_the_day_best_first_and_links_the_rest() -> None:
    day = [candidate("paper", f"p{i}") for i in range(ROUNDUP)] + [candidate("news", "n1", reviewed=False)]
    text = roundup("ESMO Congress", DAY, ranked(day), "https://guthub.tw/")
    blocks = text.split("\n\n")
    assert blocks[0] == "GutHub｜ESMO Congress 期間速報（2026-11-17）"
    # News before papers, as for the single pick; an unreviewed story still says so.
    assert blocks[1] == "【AI 未審】n1 標題\nHR 0.62，延長存活\nhttps://guthub.tw/news/n1/"
    assert len(blocks) == 1 + ROUNDUP + 1
    assert blocks[-1] == "另有 1 則：https://guthub.tw/updates/"
    assert "另有" not in roundup("ESMO Congress", DAY, ranked(day[:2]), "https://guthub.tw")
