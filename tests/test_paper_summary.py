"""At-a-glance paper summaries (I1 #190, I2 #191, ADR-0025).

The shape and number checks need nothing; the storage tests need Supabase local (GUTHUB_TEST_DATABASE_URL) and run
in a rolled-back transaction, like test_content_requests.py.
"""

import copy
import sys
from pathlib import Path

import pytest

import paper_summary
from content_store import content_session
from publish import KB, PublishError, mark_reviewed, publish_paper
from test_content_requests import FakeGh, db_writer, outcome, public, site_request  # noqa: F401
from test_publish import TODAY, _paper, kb  # noqa: F401
from validate import validate_summary

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
import content_requests  # noqa: E402

SUMMARY = {
    "title": "BREAKWATER：BRAF V600E mCRC 一線 EC + mFOLFOX6",
    "takeaway": "一線 EC + mFOLFOX6 讓中位存活從 15.1 延長到 30.3 個月",
    "question": "未治療的 BRAF V600E mCRC，一線 EC + mFOLFOX6 是否優於標準治療？",
    "population": "未治療的 BRAF V600E 轉移性大腸直腸癌，479 位",
    "comparison": "Open-label phase 3 RCT：EC + mFOLFOX6 對標準治療",
    "findings": ["mOS 30.3 vs 15.1 個月，HR 0.49", "mPFS 12.8 vs 7.1 個月"],
    "meaning": "一線加入 EC 的 PFS 與 OS 都較長。",
    "limits": ["Open-label", "OS 為期中分析"],
    "model": "claude-fable-5-2",
    "writtenAt": "2026-11-19",
    "reviewedAt": None,
}
SOURCES = "BRAF V600E; EC + mFOLFOX6; mPFS 12.8 vs 7.1 mo; mOS 30.3 vs 15.1 mo, HR 0.49; n=479; phase 3"


def test_a_well_formed_summary_passes() -> None:
    assert validate_summary("p", SUMMARY) == []
    assert paper_summary.problems(copy.deepcopy(SUMMARY), SOURCES) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"takeaway": ""}, "summary.takeaway must be 1-80"),
        ({"title": "長" * 81}, "summary.title must be 1-80"),
        ({"findings": []}, "summary.findings must be 1-4"),
        ({"limits": ["a", "b", "c", "d"]}, "summary.limits must be 1-3"),
        ({"reviewedAt": "yesterday"}, "reviewedAt must be YYYY-MM-DD or null"),
        ({"extra": "x"}, "unknown field: extra"),
        ({"meaning": "見 <b>原文</b>"}, "raw HTML"),
    ],
)
def test_a_malformed_summary_is_refused(change: dict, message: str) -> None:
    assert any(message in e for e in validate_summary("p", {**SUMMARY, **change}))


def test_a_number_in_neither_source_is_refused() -> None:
    made_up = {**SUMMARY, "findings": ["mOS 30.3 vs 15.1 個月，HR 0.51"]}
    assert paper_summary.problems(made_up, SOURCES) == ["numbers not in the sources: 0.51"]


def test_lancet_middle_dots_are_read_as_decimals() -> None:
    assert paper_summary.numbers("中位追蹤 58·7 個月") == {"58.7"}


def test_a_summary_is_stored_kept_by_later_writes_and_reviewed_with_its_paper(db_writer) -> None:  # noqa: F811
    paper_summary.save("bw-nejm-2025", SUMMARY, db_writer)
    stored = db_writer.execute("select summary from app.papers where id = 'bw-nejm-2025'").fetchone()[0]
    assert stored == SUMMARY
    # Paper Watch exports and re-imports the whole knowledge base on every write; the summary survives it.
    with content_session("publish_paper", "10.1/x", key="k-later", conn=db_writer) as session:
        session.record(publish_paper(_paper(), "auto", TODAY, session.kb)["id"])
    assert db_writer.execute("select summary from app.papers where id = 'bw-nejm-2025'").fetchone()[0] == SUMMARY
    # A hand-curated paper has nothing else to review; the admin's button confirms its summary.
    request = site_request(db_writer, "review", "paper", "bw-nejm-2025")
    assert content_requests.run(FakeGh([]), "owner/repo", TODAY, db_writer, db_writer) == 0, outcome(db_writer, request)
    reviewed = db_writer.execute("select summary->>'reviewedAt' from app.papers where id = 'bw-nejm-2025'")
    assert reviewed.fetchone()[0] is not None
    assert public(db_writer, "bw-nejm-2025")


def test_a_curated_paper_without_a_pending_summary_is_still_refused(kb: KB) -> None:  # noqa: F811
    data = kb.load()
    paper = next(p for t in data.values() for p in t.get("papers", []) if p["id"] == "kn177")
    paper["summary"] = {**SUMMARY, "reviewedAt": "2026-11-18"}
    kb.save(data)
    with pytest.raises(PublishError, match="人工整理"):
        mark_reviewed("paper", "kn177", kb)


def test_paper_watch_summarises_only_the_new_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(paper_summary, "run", lambda url, only: calls.append(only) or {"written": only})
    monkeypatch.setattr(paper_summary, "ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv(paper_summary.DATABASE_ENV, "postgresql://db")
    paper_summary.summarize_new([])
    paper_summary.summarize_new(["new-2026"])
    assert calls == [["new-2026"]]


def test_a_failed_summary_never_fails_paper_watch(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def broken(url: str, only: list[str]) -> dict:
        raise RuntimeError("PubMed is down")

    monkeypatch.setattr(paper_summary, "run", broken)
    monkeypatch.setattr(paper_summary, "ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv(paper_summary.DATABASE_ENV, "postgresql://db")
    paper_summary.summarize_new(["new-2026"])
    assert "not written: PubMed is down" in capsys.readouterr().out


def test_nothing_is_paid_for_when_the_database_is_not_the_writer(db_writer, monkeypatch) -> None:  # noqa: F811
    db_writer.execute("update app.content_writer set writer = 'json'")
    monkeypatch.setattr(paper_summary, "write", lambda *a: pytest.fail("called Claude"))

    class Same:  # run() opens its own connections; hand it the test transaction instead
        def __init__(self, *a, **k) -> None:
            pass

        def __enter__(self):
            return db_writer

        def __exit__(self, *exc) -> None:
            return None

    monkeypatch.setattr("psycopg.connect", Same)
    with pytest.raises(ValueError, match="content writer is 'json'"):
        paper_summary.run("postgresql://unused")
