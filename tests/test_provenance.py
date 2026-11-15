"""Tests for number provenance and the auto-publish gate."""

from unittest.mock import patch

import pytest

from classify import RESCUE_OUTPUT_SCHEMA, SUBMIT_CLASSIFICATION_TOOL, _apply_submission
from create_issues import format_issue_body
from fetch_rss import fetch_rss
from issue_data import extract
from provenance import (
    abstract_status,
    check_evidence,
    evaluate_commentary_gate,
    evaluate_paper_gate,
    numbers_in,
    unsourced_numbers,
)
from topic_agents import build_paper_prompt

# Shaped like issue #32 (NICHE-2, Lancet 2026), ending at a full sentence.
NICHE2_ABSTRACT = (
    "BACKGROUND: Neoadjuvant immune checkpoint blockade induces high pathological response rates. "
    "METHODS: Patients received a single dose of ipilimumab and two doses of nivolumab, followed by surgery. "
    "FINDINGS: From July 4, 2017, to July 18, 2022, 123 patients were screened, of whom 115 were treated and "
    "111 were included in the per-protocol population. At the data cutoff (June 19, 2026), the postoperative "
    "median follow-up was 58·7 months (IQR 49·0-72·9). The 3-year disease-free survival was 100% "
    "(97·5% CI 100-100). The 5-year overall survival was 100% (95% CI 100-100). "
    "INTERPRETATION: Neoadjuvant nivolumab plus ipilimumab led to durable disease control."
)

AUTO_TOPICS = {"mCRC-MSI-H"}


def _paper(**overrides) -> dict:
    paper = {
        "topic": "mCRC-MSI-H",
        "abstract": NICHE2_ABSTRACT,
        "abstract_status": "full",
        "ai_parse_failed": False,
        "ai_suggested_js": {
            "id": "niche2-os",
            "n": 111,
            "result": "3-yr DFS 100%, 5-yr OS 100%; median follow-up 58.7 mo",
            "bottomLine": "111 例零復發",
        },
        "ai_evidence": [
            {
                "claim": "n=111",
                "source": "abstract",
                "quote": "111 were included in the per-protocol population",
                "url": None,
            },
            {
                "claim": "3-yr DFS 100%",
                "source": "abstract",
                "quote": "The 3-year disease-free survival was 100% (97.5% CI 100-100)",
                "url": None,
            },
            {
                "claim": "5-yr OS 100%",
                "source": "abstract",
                "quote": "The 5-year overall survival was 100%",
                "url": None,
            },
            {
                "claim": "median follow-up 58.7 mo",
                "source": "abstract",
                "quote": "median follow-up was 58·7 months",
                "url": None,
            },
        ],
    }
    paper.update(overrides)
    return paper


class TestAbstractStatus:
    def test_full_structured(self):
        assert abstract_status(NICHE2_ABSTRACT) == "full"

    def test_missing(self):
        assert abstract_status("") == "missing"
        assert abstract_status("   ") == "missing"

    def test_cut_mid_sentence(self):
        # Issue #33 (UNICORN): the journal feed cut the abstract at 500 characters.
        assert (
            abstract_status("we evaluated short-course preoperative botensilimab in 56 patients with r") == "truncated"
        )

    def test_setup_sections_without_results(self):
        # Issue #30 (AZUR-1): only BACKGROUND survived.
        text = "BACKGROUND: Multimodal treatment is standard. METHODS: Patients received dostarlimab."
        assert abstract_status(text) == "truncated"

    def test_registration_number_ending(self):
        assert abstract_status("RESULTS: ORR was 40%. TRIAL REGISTRATION: NCT05425940") == "full"


class TestNumbers:
    def test_extracts_values_and_skips_ci_level(self):
        nums = numbers_in("mOS 30.3 vs 15.1 mo, HR 0.49 (95% CI 0.36–0.66)")
        assert nums == {"30.3", "15.1", "0.49", "0.36", "0.66"}

    def test_canonical_forms(self):
        assert numbers_in("83.0% vs 0.80; 58·7 mo; n=7,133") == {"83", "0.8", "58.7", "7133"}

    def test_skips_labels(self):
        assert numbers_in("2L+ after G3 events in NCT05425940") == set()

    def test_skips_trial_names(self):
        assert numbers_in("STELLAR-303 and NICHE-2 vs KEYNOTE-177") == set()

    def test_unsourced(self):
        evidence = [{"claim": "ORR 38.9% vs 16.7%"}]
        assert unsourced_numbers("ORR 38.9% vs 16.7% (p=0.068)", evidence) == ["0.068"]


class TestCheckEvidence:
    def test_statuses(self):
        evidence = [
            {"claim": "3-yr DFS 100%", "source": "abstract", "quote": "disease-free survival was 100%", "url": None},
            {"claim": "pCR 組 92%", "source": "abstract", "quote": "92% of patients with pCR", "url": None},
            {"claim": "cCR12 68%", "source": "web_fetch", "quote": "68%", "url": "https://example.org/azur1"},
            {"claim": "n=51", "source": "inference", "quote": None, "url": None},
            {"claim": "x", "source": "web_fetch", "quote": "x", "url": None},
        ]
        statuses = [c.status for c in check_evidence(evidence, NICHE2_ABSTRACT)]
        assert statuses == ["verified", "not_found", "web", "inference", "invalid"]

    def test_quote_matching_tolerates_middle_dot_and_spacing(self):
        evidence = [{"claim": "58.7", "source": "abstract", "quote": "median  follow-up was 58.7 months", "url": None}]
        assert check_evidence(evidence, NICHE2_ABSTRACT)[0].status == "verified"


class TestPaperGate:
    def test_passes_when_every_number_is_in_the_abstract(self):
        result = evaluate_paper_gate(_paper(), AUTO_TOPICS)
        assert result.passed, result.reasons

    def test_fabricated_number_is_held(self):
        # Issue #32: the AI added "pCR 組 92%", which is in no source.
        paper = _paper()
        paper["ai_suggested_js"]["result"] += "; pCR 組 92%"
        paper["ai_evidence"].append(
            {"claim": "pCR 組 92%", "source": "abstract", "quote": "92% in the pCR group", "url": None}
        )
        result = evaluate_paper_gate(paper, AUTO_TOPICS)
        assert not result.passed
        assert any("摘要中找不到" in r for r in result.reasons)
        assert any("92" in r for r in result.reasons)

    def test_number_without_evidence_is_held(self):
        paper = _paper()
        paper["ai_suggested_js"]["result"] += "; 123 screened"
        result = evaluate_paper_gate(paper, AUTO_TOPICS)
        assert any("沒有附出處" in r and "123" in r for r in result.reasons)

    def test_inferred_n_is_held(self):
        # Issue #28: n=51 was inferred (15 + 36), not stated in the abstract.
        paper = _paper()
        paper["ai_suggested_js"]["n"] = 51
        paper["ai_evidence"].append({"claim": "n=51", "source": "inference", "quote": None, "url": None})
        result = evaluate_paper_gate(paper, AUTO_TOPICS)
        assert not result.passed
        assert any("推論" in r for r in result.reasons)

    @pytest.mark.parametrize("status", ["truncated", "missing"])
    def test_incomplete_abstract_is_held(self, status):
        result = evaluate_paper_gate(_paper(abstract_status=status), AUTO_TOPICS)
        assert not result.passed

    def test_unsupported_topic_is_held(self):
        result = evaluate_paper_gate(_paper(topic="robotic-surgery"), AUTO_TOPICS)
        assert any("不支援自動發布" in r for r in result.reasons)

    def test_parse_failure_is_held(self):
        result = evaluate_paper_gate(_paper(ai_parse_failed=True, ai_suggested_js=None, ai_evidence=[]), AUTO_TOPICS)
        assert not result.passed


class _Proposal:
    def __init__(self, match_method="comment_on", new_data=False, summary="評論 STELLAR-303 的意義"):
        self.match_method, self.new_data, self.summary = match_method, new_data, summary


class TestCommentaryGate:
    def test_comment_on_without_new_data_passes(self):
        assert evaluate_commentary_gate(_Proposal(), "abstract").passed

    def test_ai_match_is_held(self):
        assert not evaluate_commentary_gate(_Proposal(match_method="ai"), "abstract").passed

    def test_new_data_is_held(self):
        assert not evaluate_commentary_gate(_Proposal(new_data=True), "abstract").passed

    def test_number_not_in_abstract_is_held(self):
        result = evaluate_commentary_gate(_Proposal(summary="OS HR 0.80"), "no numbers here.")
        assert not result.passed


class TestSchema:
    def test_evidence_required_in_tool_and_rescue(self):
        assert "evidence" in SUBMIT_CLASSIFICATION_TOOL["input_schema"]["required"]
        assert "evidence" in RESCUE_OUTPUT_SCHEMA["required"]

    def test_apply_submission_keeps_evidence(self):
        paper = _apply_submission({}, {"relevance_score": 4, "contextual_analysis": "x", "evidence": [{"claim": "a"}]})
        assert paper["ai_evidence"] == [{"claim": "a"}]


class TestIssueBody:
    def test_truncated_abstract_warning_comes_first(self):
        body = format_issue_body(_paper(abstract_status="truncated", ai_score=4, title="t"))
        assert body.startswith("> [!WARNING]")
        assert "摘要被截斷" in body.splitlines()[1]

    def test_provenance_table_and_gate_reasons(self):
        paper = _paper(ai_score=4, gate_reasons=["出處未通過（摘要中找不到）：pCR 組 92%"])
        body = format_issue_body(paper)
        assert "## 數字出處" in body
        assert "✓ 摘要中找到" in body
        assert "未自動發布" in body
        assert "`accepted` label" in body

    def test_payload_round_trips(self):
        paper = _paper(ai_score=4, title="NICHE-2", doi="10.1016/x")
        payload = extract(format_issue_body(paper), "paper")
        assert payload["ai_suggested_js"]["id"] == "niche2-os"
        assert payload["ai_evidence"] == paper["ai_evidence"]
        assert payload["abstract"] == NICHE2_ABSTRACT

    def test_full_abstract_shown(self):
        long_abstract = "A" * 3000 + "."
        body = format_issue_body(_paper(abstract=long_abstract, ai_score=4))
        assert long_abstract in body


class TestPrompt:
    def test_truncated_abstract_note(self):
        prompt = build_paper_prompt({"title": "t", "abstract": "cut", "abstract_status": "truncated"})
        assert "此摘要被截斷" in prompt

    def test_full_abstract_no_note(self):
        assert "⚠" not in build_paper_prompt({"title": "t", "abstract": "ok.", "abstract_status": "full"})


@patch("fetch_rss.efetch")
@patch("fetch_rss.esearch", return_value=["1"])
@patch("fetch_rss.load_tracked_dois", return_value={})
@patch("fetch_rss.load_queries")
def test_journal_feed_keeps_full_abstract(mock_queries, mock_tracked, mock_esearch, mock_efetch):
    """The 500-character cut that starved #30 / #33 of their results is gone."""
    mock_queries.return_value = {
        "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF", "colorectal"]},
        "rss_feeds": [{"name": "NEJM", "pubmed_journal": "N Engl J Med"}],
    }
    abstract = "BRAF colorectal " + "x" * 2000 + "."
    mock_efetch.return_value = [{"pmid": "1", "doi": "10.1/a", "title": "BRAF colorectal", "abstract": abstract}]
    assert fetch_rss()[0]["abstract"] == abstract
