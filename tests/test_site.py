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


def test_index_has_disclaimer_and_no_dead_entries():
    html = (ROOT / "index.html").read_text()
    assert 'class="disclaimer-footer"' in html
    assert 'id="disclaimer-notice"' in html
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
