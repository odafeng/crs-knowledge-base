"""Build and publication contracts for the replacement site."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
from newsroom.gate import unsupported
from sitegen.load import _clean_html, load_kb
from sitegen.render import build_site
from sitegen.urls import relative

ROOT = Path(__file__).resolve().parent.parent


def test_source_links_keep_their_text_without_publishing_old_urls():
    assert _clean_html('<p><a href="docs/test.html">Trial detail</a></p>') == "<p>Trial detail</p>"


def test_build_records_the_revision_and_changes_cache_when_it_changes(tmp_path, monkeypatch):
    kb = load_kb(ROOT / "data/papers.json")
    out = tmp_path / "site"
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    build_site(kb, out)
    assert json.loads((out / "build-info.json").read_text()) == {"commit": "a" * 40}
    before = (out / "sw.js").read_text()
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    build_site(kb, out)
    assert json.loads((out / "build-info.json").read_text()) == {"commit": "b" * 40}
    assert (out / "sw.js").read_text() != before


def test_build_replaces_site_without_redirects(built_site):
    out, stats = built_site
    assert stats["pages"] == 76
    assert not (out / "docs").exists()
    for page in out.rglob("*.html"):
        text = page.read_text()
        assert 'http-equiv="refresh"' not in text
        assert "location.replace" not in text
        assert "不構成醫療建議" in text
        assert text.count("<h1") == 1, page


def test_news_is_gated_and_unreviewed_pages_are_not_indexed(built_site):
    out, _ = built_site
    raw = json.loads((ROOT / "data/papers.json").read_text())
    papers = {p["id"]: p for block in raw.values() for p in block.get("papers", [])}
    stories = json.loads((ROOT / "data/news.json").read_text())
    assert len(stories) == 7
    sitemap = (out / "sitemap.xml").read_text()
    for story in stories:
        assert unsupported(story, papers[story["paperId"]]) == []
        assert story["review"]["status"] == "auto"
        html = (out / "news" / story["id"] / "index.html").read_text()
        assert 'content="noindex, follow"' in html
        assert f"/news/{story['id']}/" not in sitemap


def test_preserves_detailed_evidence_in_new_template(built_site):
    out, _ = built_site
    text = (out / "papers/niche2-os/index.html").read_text()
    assert "58.7 個月" in text
    assert "ctDNA 清除率取自二手報導" in text
    assert "詳細證據整理" in text
    assert '<link rel="stylesheet" href="../../styles/site.css">' in text
    robotic = (out / "robotic/tme/index.html").read_text()
    assert "Short-term outcomes in robotic-assisted" in robotic


def test_all_links_search_and_metadata_are_valid(built_site):
    out, stats = built_site
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/check_links.py"), str(out)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert stats["feeds"] == 10
    for path in out.rglob("*.xml"):
        ElementTree.parse(path)
    index = json.loads((out / "search.json").read_text())
    assert len(index) == 60
    for entry in index:
        assert (out / entry["path"].lstrip("/") / "index.html").is_file()
    for page in out.rglob("*.html"):
        for payload in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page.read_text(), re.S):
            json.loads(payload)


@pytest.mark.parametrize(
    ("target", "current", "expected"),
    [("/", "/papers/beacon-2019/", "../../"), ("/mcrc/msi-h/", "/", "mcrc/msi-h/")],
)
def test_relative_urls(target, current, expected):
    assert relative(target, current) == expected


def test_build_without_news_and_empty_topic(tmp_path):
    raw = json.loads((ROOT / "data/papers.json").read_text())
    raw["mCRC-HER2"]["papers"] = []
    kb_path = tmp_path / "papers.json"
    kb_path.write_text(json.dumps(raw))
    out = tmp_path / "site"
    build_site(load_kb(kb_path), out)
    assert (out / "mcrc/her2/index.html").is_file()
    assert not (out / "feed/her2.xml").exists()


def test_build_rejects_unsupported_news_numbers(tmp_path):
    news = json.loads((ROOT / "data/news.json").read_text())
    news[0]["dek"] += " 98765 patients."
    path = tmp_path / "news.json"
    path.write_text(json.dumps(news))
    with pytest.raises(ValueError, match="98765"):
        load_kb(ROOT / "data/papers.json", path)


def test_build_does_not_delete_unrelated_files(tmp_path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("user content")
    with pytest.raises(ValueError, match="output"):
        build_site(load_kb(ROOT / "data/papers.json"), tmp_path)
    assert sentinel.read_text() == "user content"


def test_rebuild_removes_unpublished_pages_and_changes_cache_version(tmp_path):
    from dataclasses import replace

    kb = load_kb(ROOT / "data/papers.json", ROOT / "data/news.json")
    out = tmp_path / "site"
    build_site(kb, out)
    before = (out / "sw.js").read_text()
    build_site(replace(kb, news=kb.news[1:]), out)
    assert not (out / "news" / kb.news[0].id).exists()
    assert (out / "sw.js").read_text() != before


def test_pipeline_publish_build_and_unpublish(tmp_path):
    from publish import KB, publish_paper, unpublish
    from test_publish import _paper

    shutil.copytree(ROOT / "data", tmp_path / "data")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    (tmp_path / "data/WRITER").write_text("json\n")  # a JSON-writer copy, whichever writer the repository has now
    kb = KB(tmp_path)
    publish_paper(_paper(), "auto", "2026-11-16", kb)
    out = tmp_path / "site"
    build_site(load_kb(kb.papers_json, tmp_path / "data/news.json"), out)
    html = (out / "papers/test-auto-2026/index.html").read_text()
    assert "&lt;script&gt;" in html and "&amp;lt;script&amp;gt;" not in html
    assert "✓ 摘要中找到" in html
    assert 'content="noindex, follow"' in html
    unpublish("test-auto-2026", kb)
    build_site(load_kb(kb.papers_json, tmp_path / "data/news.json"), out)
    assert not (out / "papers/test-auto-2026").exists()


def test_unpublish_also_removes_news_about_the_paper(tmp_path):
    from publish import KB, publish_paper, unpublish
    from test_publish import _paper

    shutil.copytree(ROOT / "data", tmp_path / "data")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    (tmp_path / "data/WRITER").write_text("json\n")  # a JSON-writer copy, whichever writer the repository has now
    kb = KB(tmp_path)
    publish_paper(_paper(), "auto", "2026-11-16", kb)
    stories = json.loads(kb.news_json.read_text())
    kb.news_json.write_text(json.dumps([*stories, {"id": "test-news", "paperId": "test-auto-2026"}]))
    unpublish("test-auto-2026", kb)
    assert json.loads(kb.news_json.read_text()) == stories
