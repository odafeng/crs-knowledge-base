"""Tests for automatic Paper Watch -> /news/ story generation (K2 #252)."""

import copy
import json
from typing import Any

import import_content
import pytest

import news_writer
from publish import KB, PublishError, mark_reviewed, publish_news, unpublish_story
from test_publish import kb  # noqa: F401

PAPER: dict[str, Any] = {
    "id": "bw-nejm-2025",
    "regimen": "EC+mFOLFOX6 vs SOC (1L)",
    "studyType": "Phase 3 RCT (updated)",
    "n": 479,
    "endpoint": "PFS by BICR + OS",
    "result": "mPFS 12.8 vs 7.1 mo; mOS 30.3 vs 15.1 mo, HR 0.49 (95% CI 0.38-0.63), ORR 61% vs 40%",
    "bottomLine": "一線 EC + mFOLFOX6 顯著延長中位存活至 30.3 個月",
    "journal": "NEJM",
    "year": 2025,
}


def _story(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "bw-nejm-2025",
        "paperId": "bw-nejm-2025",
        "publishedAt": "2026-11-24",
        "headline": ["BREAKWATER：", "一線 EC + mFOLFOX6 ", "mOS 達 30.3 個月"],
        "dek": "收案 479 位的 Phase 3 RCT 顯示，一線 EC + mFOLFOX6 的 mOS 為 30.3 個月，對照組為 15.1 個月（HR 0.49）。",
        "key": {"label": "中位整體存活（mOS）", "value": "30.3", "unit": "個月"},
        "figures": [
            {
                "kind": "compare",
                "armA": "EC + mFOLFOX6",
                "armB": "SOC",
                "rows": [
                    {"label": "mOS", "unit": "個月", "a": 30.3, "b": 15.1},
                    {"label": "mPFS", "unit": "個月", "a": 12.8, "b": 7.1},
                ],
            },
            {
                "kind": "interval",
                "label": "整體存活 HR",
                "point": 0.49,
                "low": 0.38,
                "high": 0.63,
                "note": "95% CI",
            },
        ],
        "figureNote": "數字出處：NEJM 2025，Phase 3 RCT。",
        "body": [
            {
                "heading": "發生了什麼",
                "text": "這項收案 479 位的 Phase 3 RCT 比較一線 EC + mFOLFOX6 與標準治療，mOS 為 30.3 對 15.1 個月，ORR 為 61% 對 40%。",
            },
            {
                "heading": "為什麼重要",
                "text": "在存活指標達到 HR 0.49（95% CI 0.38–0.63），為一線治療提供明確隨機對照證據。",
            },
            {
                "heading": "限制",
                "text": "仍須留意追蹤時間與族群篩選條件。",
            },
            {
                "heading": "對臨床的意義",
                "text": "可作為臨床團隊討論一線合併方案時的核心參考依據。",
            },
        ],
        "review": {"status": "auto", "publishedAt": "2026-11-24"},
    }
    return base | changes


def test_well_formed_story_passes_validation_and_number_gate() -> None:
    assert news_writer.problems(_story(), PAPER) == []
    without_note = _story()
    del without_note["figureNote"]
    assert news_writer.problems(without_note, PAPER) == []


def test_unsupported_number_in_any_field_is_refused() -> None:
    bad_dek = _story(dek="死亡風險降低 51%，共 479 人。")
    assert any("51" in err for err in news_writer.problems(bad_dek, PAPER))

    bad_fig = _story(figures=[{"kind": "numbers", "stats": [{"label": "ORR", "value": "62", "unit": "%"}]}])
    assert any("62" in err for err in news_writer.problems(bad_fig, PAPER))


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"id": "Bad_ID"}, "id must match"),
        ({"headline": ["單段"]}, "2-4 non-empty strings"),
        ({"dek": ""}, "dek must be 1-180"),
        ({"body": [{"heading": "摘要", "text": "內容"}, {"heading": "限制", "text": "內容"}]}, "發生了什麼"),
        ({"body": [{"heading": "發生了什麼", "text": "內容"}, {"heading": "限制", "text": "內容"}]}, "為什麼重要"),
        ({"dek": "見 <b>原文</b>"}, "raw HTML"),
        (
            {"figures": [{"kind": "interval", "label": "HR", "point": 0.49, "low": 0.05, "high": 0.63}]},
            "0.1 <= low <= point <= high <= 8.0",
        ),
        (
            {"figures": [{"kind": "meters", "rows": [{"label": "ORR", "percent": 120}]}]},
            "between 0 and 100",
        ),
        (
            {
                "figures": [
                    {
                        "kind": "compare",
                        "armA": "A",
                        "armB": "B",
                        "rows": [{"label": "mOS", "unit": "個月", "a": 0, "b": 0}],
                    }
                ]
            },
            "positive maximum",
        ),
    ],
)
def test_malformed_story_is_refused(change: dict[str, Any], fragment: str) -> None:
    errs = news_writer.validate_story(_story(**change))
    assert any(fragment in e for e in errs), errs


def test_less_than_sign_in_statistics_is_not_html() -> None:
    story = _story(dek="一線治療 mOS 30.3 個月（P<0.49）。")
    assert news_writer.validate_story(story) == []


def test_is_newsworthy_and_select_candidates() -> None:
    published = [
        {"kb_id": "retro-2026", "ai_score": 4, "ai_suggested_js": {"studyType": "Retrospective cohort"}},
        {"kb_id": "phase2-2026", "ai_score": 4, "ai_suggested_js": {"studyType": "Phase 2 RCT"}},
        {"kb_id": "cohort-breakthrough", "ai_score": 5, "ai_suggested_js": {"studyType": "Prospective cohort"}},
        {"kb_id": "phase3-2026", "ai_score": 5, "ai_suggested_js": {"studyType": "Phase 3 RCT"}},
    ]
    assert not news_writer.is_newsworthy({"studyType": "Retrospective cohort"}, score=4)
    assert news_writer.is_newsworthy({"studyType": "Prospective cohort"}, score=5)
    assert news_writer.is_newsworthy({"studyType": "Phase 3 RCT"}, score=4)
    # Score-3 papers auto-publish (K14 #308, ADR-0032) but never get an automatic story.
    assert not news_writer.is_newsworthy({"studyType": "Phase 3 RCT"}, score=3)
    # Capped at MAX_STORIES_PER_RUN (2), score 5 Phase 3 first, then score 5 cohort
    assert news_writer.select_candidates(published) == ["phase3-2026", "cohort-breakthrough"]


def test_story_id_for_sanitizes_and_avoids_collisions() -> None:
    assert news_writer.story_id_for("BW_NEJM_2025", set()) == "bw-nejm-2025"
    assert news_writer.story_id_for("bw-nejm-2025", {"bw-nejm-2025"}) == "bw-nejm-2025-2"
    assert news_writer.story_id_for("bw-nejm-2025", {"bw-nejm-2025", "bw-nejm-2025-2"}) == "bw-nejm-2025-3"


def test_resolve_story_id_reuses_existing_id_on_redo() -> None:
    taken = {"bw-nejm-2025", "other-story"}
    existing = {"bw-nejm-2025": "bw-nejm-2025"}
    assert news_writer.resolve_story_id("bw-nejm-2025", taken, existing, redo=True) == "bw-nejm-2025"
    assert news_writer.resolve_story_id("bw-nejm-2025", taken, existing, redo=False) == "bw-nejm-2025-2"


def test_interval_figure_requires_source_confirmed_95_ci() -> None:
    paper_90 = PAPER | {
        "result": "mPFS 12.8 vs 7.1 mo; mOS 30.3 vs 15.1 mo, HR 0.49 (90% CI 0.38-0.63), ORR 61% vs 40%"
    }
    story_90 = _story(
        figures=[
            {"kind": "interval", "label": "整體存活 HR", "point": 0.49, "low": 0.38, "high": 0.63, "note": "90% CI"}
        ],
        body=[
            {"heading": "發生了什麼", "text": "收案 479 位的 Phase 3 RCT，mOS 30.3 vs 15.1 個月。"},
            {"heading": "為什麼重要", "text": "整體存活 HR 0.49（90% CI 0.38–0.63）。"},
        ],
    )
    errs = news_writer.problems(story_90, paper_90)
    assert any("95% CI" in e for e in errs), errs

    # Even if <entry> mentions 95% CI elsewhere, an interval figure noting 90% CI is refused.
    paper_mixed = PAPER | {"result": PAPER["result"] + "; 90% CI 0.38-0.63"}
    errs_mixed = news_writer.problems(story_90, paper_mixed)
    assert any("90%" in e for e in errs_mixed), errs_mixed


def test_draft_retries_once_when_first_attempt_has_unsupported_number(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[list[str] | None] = []
    bad = _story(dek="死亡風險降低 51%。")
    good = _story()

    def fake_write(_client: Any, _paper: dict[str, Any], _sid: str, _today: str, refused: list[str] | None = None):
        attempts.append(refused)
        return copy.deepcopy(bad if refused is None else good)

    monkeypatch.setattr(news_writer, "write", fake_write)
    story, found = news_writer.draft(object(), PAPER, "bw-nejm-2025", "2026-11-24")  # type: ignore[arg-type]
    assert found == []
    assert story == good
    assert len(attempts) == 2
    assert attempts[0] is None
    assert attempts[1] and any("51" in msg for msg in attempts[1])


def test_publish_news_integrates_with_load_kb_review_and_unpublish(kb: KB) -> None:  # noqa: F811
    data = kb.load()
    paper = next(p for t in data.values() for p in t.get("papers", []) if p["id"] == "kn177")
    story = _story(
        id="kn177-auto-test",
        paperId="kn177",
        headline=[f"{paper['regimen']}：", f"{paper['journal']} {paper['year']} 重點更新"],
        dek=f"{paper['journal']} {paper['year']} 針對 MSI-H 轉移性大腸癌的治療結果。",
        key={"label": "發表年份", "value": str(paper["year"]), "unit": "年"},
        figures=[],
        figureNote=f"數字出處：{paper['journal']} {paper['year']}。",
        body=[
            {
                "heading": "發生了什麼",
                "text": f"這篇發表於 {paper['journal']} {paper['year']} 的研究評估了一線免疫治療。",
            },
            {"heading": "對臨床的意義", "text": "提供 MSI-H 病人一線治療選擇的重要實證。"},
        ],
    )
    publish_news(story, kb)
    built = import_content.build_rows(kb.root)
    assert built.errors == []
    assert any(n["id"] == "kn177-auto-test" and n["review_status"] == "auto" for n in built.tables["news"])

    # Duplicate paperId is refused unless replace=True
    with pytest.raises(PublishError, match="已有對應新聞"):
        publish_news(story | {"id": "kn177-auto-test-2"}, kb)

    # Admin can mark reviewed and unpublish the auto-generated story
    assert mark_reviewed("news", "kn177-auto-test", kb) == "review news kn177-auto-test"
    saved = json.loads(kb.news_json.read_text(encoding="utf-8"))
    assert next(s for s in saved if s["id"] == "kn177-auto-test")["review"]["status"] == "accepted"
    assert unpublish_story("kn177-auto-test", kb) == "news kn177-auto-test"


def test_write_news_for_new_is_non_fatal_and_filters_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(_url: str, only: list[str] | None = None, *, today: str | None = None, **_kw: Any) -> dict[str, Any]:
        calls.append((only or [], today))
        return {"written": []}

    monkeypatch.setattr(news_writer, "run", fake_run)
    monkeypatch.setattr(news_writer, "ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv(news_writer.DATABASE_ENV, "postgresql://db")

    news_writer.write_news_for_new(
        [
            {"kb_id": "retro-1", "ai_score": 4, "ai_suggested_js": {"studyType": "Retrospective cohort"}},
            {"kb_id": "rct-1", "ai_score": 5, "ai_suggested_js": {"studyType": "Phase 3 RCT"}},
        ],
        today="2026-11-24",
    )
    assert calls == [(["rct-1"], "2026-11-24")]

    # Exceptions must never propagate out to fail Paper Watch
    monkeypatch.setattr(news_writer, "run", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    news_writer.write_news_for_new(
        [{"kb_id": "rct-2", "ai_score": 5, "ai_suggested_js": {"studyType": "Phase 3 RCT"}}],
        today="2026-11-24",
    )
