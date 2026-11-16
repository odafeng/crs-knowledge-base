"""Static checks on the published site files."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOC_NOTE = "不構成醫療建議"


@pytest.mark.parametrize("doc", sorted((ROOT / "docs").rglob("*.html")), ids=lambda p: p.name)
def test_every_detail_page_has_disclaimer(doc):
    assert DOC_NOTE in doc.read_text()


def test_generated_pages_have_disclaimer():
    import json

    from publish import build_entry, render_doc_page
    from test_publish import _paper

    paper = _paper()
    data = json.loads((ROOT / "data" / "papers.json").read_text())
    assert DOC_NOTE in render_doc_page(paper, build_entry(paper, data, "auto", "2026-11-15"))


def test_index_has_disclaimer_and_no_dead_entries(built_site):
    out, _ = built_site
    html = (out / "index.html").read_text()
    assert DOC_NOTE in html
    assert "內容建置中" not in html


def test_every_paper_has_source_and_review_date():
    import json

    from validate import validate_data

    data = json.loads((ROOT / "data" / "papers.json").read_text())
    paper = data["mCRC-MSI-H"]["papers"][0]
    paper["source"] = "vibes"
    del paper["reviewedAt"]
    errors = validate_data(data)
    assert any("unknown source" in e for e in errors)
    assert any("reviewedAt must be YYYY-MM-DD" in e for e in errors)


def test_added_date_is_optional_but_must_be_a_date_not_after_review():
    import json

    from validate import validate_data

    data = json.loads((ROOT / "data" / "papers.json").read_text())
    paper = data["mCRC-MSI-H"]["papers"][0]
    paper["addedAt"] = "2026/08/19"
    assert any("addedAt must be YYYY-MM-DD" in e for e in validate_data(data))
    paper["addedAt"] = "2999-01-01"
    assert any("addedAt is after reviewedAt" in e for e in validate_data(data))
    paper["addedAt"] = paper["reviewedAt"]
    assert validate_data(data) == []


def test_papers_list_on_the_date_paper_watch_found_them():
    """addedAt (the Paper Watch issue date) dates a hand-added paper; reviewedAt stays the last check (#26-#34)."""
    import json
    from datetime import date

    from sitegen.load import load_kb

    kb = load_kb(ROOT / "data" / "papers.json")
    by_id = {p.id: p for p in kb.papers}
    assert by_id["li2026-ww-mono"].published_at == date(2026, 8, 19)
    assert by_id["nccn-colon-2026"].published_at == date(2026, 11, 13)
    assert by_id["li2026-ww-mono"].reviewed_at == date(2026, 11, 15)
    raw = json.loads((ROOT / "data" / "papers.json").read_text())
    undated = [p["id"] for b in raw.values() for p in b.get("papers", []) if "addedAt" not in p]
    assert all(by_id[i].published_at == by_id[i].reviewed_at for i in undated)
    assert len({u.date for u in kb.updates() if u.kind == "paper"}) > 2


def test_news_about_those_papers_carries_the_same_date():
    from sitegen.load import load_kb

    kb = load_kb(ROOT / "data" / "papers.json", ROOT / "data" / "news.json")
    for story in kb.news:
        if story.paper.published_at != story.paper.reviewed_at:  # a paper dated by its Paper Watch issue
            assert story.published_at == story.paper.published_at, story.id
    assert len({story.published_at for story in kb.news}) > 2


def test_treatment_sections_come_from_json():
    import json

    from validate import validate_data

    data = json.loads((ROOT / "data" / "papers.json").read_text())
    for topic in ("mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H", "mCRC-HER2"):
        assert data[topic]["standard_of_care"]["cards"], topic

    card = data["mCRC-BRAF-V600E"]["standard_of_care"]["cards"][0]
    card["refs"].append("no-such-paper")
    card["regulatory"][0]["nhi"] = "maybe"
    errors = validate_data(data)
    assert any("cites unknown paper 'no-such-paper'" in e for e in errors)
    assert any("unknown nhi" in e for e in errors)


def test_home_has_search_latest_and_paper_links(built_site):
    out, _ = built_site
    html = (out / "index.html").read_text()
    assert 'aria-label="搜尋消息與文獻"' in html
    assert "新收錄文獻" in html
    assert 'href="papers/' in html
    search = (out / "updates/index.html").read_text()
    assert 'id="q"' in search and 'id="search-results"' in search
