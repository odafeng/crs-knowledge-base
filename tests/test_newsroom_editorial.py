"""Tests for N3 #288: primary-source re-verification, ranking, structured drafting, classification holds, and budget caps."""

from datetime import date

from newsroom.editorial import (
    BudgetGuard,
    run_editorial_batch,
    select_candidates,
    verify_candidate_source,
)

SOURCE_HTML = (
    b"<html><body><h1>FDA approves encorafenib plus cetuximab and mFOLFOX6 for BRAF V600E mCRC</h1>"
    b"<p>In the BREAKWATER Phase 3 randomized trial, first-line encorafenib plus cetuximab and mFOLFOX6 "
    b"improved median overall survival to 30.3 months versus 15.1 months (HR 0.49; 95% CI 0.36-0.67).</p>"
    b"</body></html>"
)


def _good_draft(url: str, *, primary: str = "colorectal-oncology", confidence: str = "high") -> dict:
    return {
        "headline": "FDA 核准一線 BRAF V600E 轉移性大腸直腸癌合併療法",
        "what_happened": "美國 FDA 依據 BREAKWATER Phase 3 隨機試驗核准 encorafenib 併用 cetuximab 與 mFOLFOX6。",
        "why_it_matters": "中位整體存活期由 15.1 個月延長至 30.3 個月（HR 0.49），確立一線治療地位。",
        "clinical_relevance": "對台灣臨床醫師而言，初診斷 mCRC 應及早完成 BRAF V600E 檢測以規劃一線方案。",
        "evidence_limitations": "本訊息為美國 FDA 核准進度，台灣 TFDA 適應症與健保給付仍須以本地公告為準。",
        "primary_domain": primary,
        "secondary_domains": [],
        "classification_confidence": confidence,
        "claims": [
            {
                "claim_text": "中位整體存活期為 30.3 個月對照 15.1 個月（HR 0.49）",
                "evidence_quote": "improved median overall survival to 30.3 months versus 15.1 months (HR 0.49; 95% CI 0.36-0.67)",
                "source_url": url,
            }
        ],
    }


def test_unreachable_or_summary_only_candidate_is_rejected_by_backend_verification() -> None:
    cand = {
        "dedup_key": "k1",
        "title": "ChatGPT summary without reachable source",
        "canonical_url": "https://dead.example/article",
        "raw_metadata": {"external_summary": "Untrusted summary claiming 100% cure."},
    }
    res = verify_candidate_source(cand, fetcher=lambda _u: (_ for _ in ()).throw(OSError("404")))
    assert res.ok is False
    assert "primary source fetch failed" in (res.rejection_reason or "")


def test_selection_prioritizes_taiwan_regulatory_and_applies_domain_diversity_cap() -> None:
    today = date(2026, 11, 28)
    cands = [
        {
            "dedup_key": f"us-{i}",
            "title": f"Colorectal cancer study {i}",
            "canonical_url": f"https://example.org/us/{i}",
            "event_type": "clinical",
            "geography": "us",
            "trust_tier": "tier2",
            "published_at": "2026-11-27",
            "primary_domain_hint": "colorectal-oncology",
            "verified_source_text": "colorectal cancer trial text " * 10,
        }
        for i in range(5)
    ] + [
        {
            "dedup_key": "tw-nhi",
            "title": "健保署新增大腸直腸癌給付條文",
            "canonical_url": "https://info.nhi.gov.tw/news/1",
            "event_type": "regulatory",
            "geography": "taiwan",
            "trust_tier": "tier1",
            "published_at": "2026-11-28",
            "primary_domain_hint": "colorectal-oncology",
            "verified_source_text": "台灣健保給付大腸直腸癌藥物規定 " * 10,
        }
    ]
    selected = select_candidates(cands, today=today, max_candidates=10, max_per_domain=3)
    assert len(selected) == 3
    assert selected[0]["dedup_key"] == "tw-nhi"


def test_unknown_domain_hint_or_low_confidence_routes_to_manual_classification_hold() -> None:
    url = "https://www.fda.gov/drugs/breakwater-2026"
    cands = [
        {
            "dedup_key": "unknown-hint",
            "title": "Colorectal FDA update",
            "canonical_url": url,
            "event_type": "regulatory",
            "geography": "us",
            "published_at": "2026-11-28",
            "primary_domain_hint": "invented-unknown-slug",
        },
        {
            "dedup_key": "low-conf",
            "title": "Colorectal low confidence update",
            "canonical_url": "https://www.fda.gov/drugs/low-conf",
            "event_type": "clinical",
            "geography": "global",
            "published_at": "2026-11-28",
            "primary_domain_hint": "colorectal-oncology",
        },
    ]

    def fake_caller(prompt: str, _schema: dict):
        if "low-conf" in prompt:
            return _good_draft("https://www.fda.gov/drugs/low-conf", confidence="low"), 0.05
        return _good_draft(url, primary="colorectal-oncology", confidence="high"), 0.05

    report = run_editorial_batch(
        cands,
        today=date(2026, 11, 28),
        fetcher=lambda _u: SOURCE_HTML,
        model_caller=fake_caller,
        budget=BudgetGuard(),
    )
    by_key = {d.candidate_key: d for d in report.drafts}
    assert by_key["unknown-hint"].status == "held_classification"
    assert by_key["low-conf"].status == "held_classification"


def test_daily_draft_cap_and_monthly_budget_cap_stop_llm_calls_deterministically() -> None:
    cands = [
        {
            "dedup_key": f"ev-{i}",
            "title": f"Colorectal approval {i}",
            "canonical_url": f"https://www.fda.gov/drugs/crc-{i}",
            "event_type": "regulatory",
            "geography": "us",
            "published_at": "2026-11-28",
            "primary_domain_hint": [
                "colorectal-oncology",
                "endoscopy",
                "minimally-invasive-surgery",
                "perioperative-care-nutrition",
            ][i],
        }
        for i in range(4)
    ]

    calls = 0

    def counting_caller(_prompt: str, _schema: dict):
        nonlocal calls
        calls += 1
        return _good_draft("https://www.fda.gov/drugs/crc-0"), 0.10

    # Daily draft cap = 3 stops before drafting the 4th item.
    report = run_editorial_batch(
        cands,
        today=date(2026, 11, 28),
        fetcher=lambda _u: SOURCE_HTML,
        model_caller=counting_caller,
        budget=BudgetGuard(monthly_spent_usd=0.0, monthly_cap_usd=20.0, max_daily_drafts=3),
    )
    assert calls == 3
    assert report.status == "budget_stopped"
    assert "daily draft cap" in (report.stopped_reason or "")

    # Monthly budget cap stops immediately with 0 LLM calls when already at USD 20.0.
    calls = 0
    capped = run_editorial_batch(
        cands,
        today=date(2026, 11, 28),
        fetcher=lambda _u: SOURCE_HTML,
        model_caller=counting_caller,
        budget=BudgetGuard(monthly_spent_usd=20.0, monthly_cap_usd=20.0),
    )
    assert calls == 0
    assert capped.status == "budget_stopped"
    assert "monthly budget cap" in (capped.stopped_reason or "")
