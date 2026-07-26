"""Tests for AI classification layer."""

from unittest.mock import MagicMock, patch

import httpx
from anthropic import APIError

from classify import classify_all, classify_paper


def _mock_submit_classification(result_dict, *, with_research_tool=False):
    """Create mock API responses that end with submit_classification tool call."""
    responses = []

    if with_research_tool:
        # First response: agent uses a research tool
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "lookup_existing_papers"
        tool_block.input = {"topic": "mCRC-BRAF-V600E"}
        tool_block.id = "tool_123"
        tool_response.content = [tool_block]
        responses.append(tool_response)

    # Final response: submit_classification
    final = MagicMock()
    final.stop_reason = "tool_use"
    submit_block = MagicMock()
    submit_block.type = "tool_use"
    submit_block.name = "submit_classification"
    submit_block.input = result_dict
    submit_block.id = "submit_1"
    final.content = [submit_block]
    responses.append(final)

    return responses


class TestClassifyAll:
    def test_skips_when_no_api_key(self, sample_candidate):
        with patch("classify.ANTHROPIC_API_KEY", ""):
            results = classify_all([sample_candidate])
        assert len(results) == 1
        assert results[0]["ai_score"] is None
        assert "skipped" in results[0]["ai_analysis"]

    def test_empty_candidates(self):
        results = classify_all([])
        assert results == []

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_dry_run_skips_api(self, sample_candidate):
        results = classify_all([sample_candidate], dry_run=True)
        assert len(results) == 1
        assert results[0]["ai_analysis"] == "(dry run)"

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_api_error_routes_remaining_papers_to_manual_review(self, sample_candidate):
        second_candidate = sample_candidate | {
            "doi": "10.1056/NEJMoa8888888",
            "pmid": "87654321",
            "title": "Second candidate",
        }
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        error = APIError("You have reached your specified API usage limits.", request, body=None)

        with (
            patch("classify.Anthropic", return_value=MagicMock()),
            patch("classify.classify_paper", side_effect=error) as mock_classify_paper,
        ):
            results = classify_all([sample_candidate.copy(), second_candidate.copy()])

        assert mock_classify_paper.call_count == 1
        assert len(results) == 2
        for result in results:
            assert result["ai_score"] is None
            assert result["ai_parse_failed"] is True
            assert "quota or rate limit" in result["ai_analysis"]
            assert "manual review" in result["ai_analysis"]


class TestClassifyPaper:
    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_structured_output_via_tool(self, sample_candidate):
        """Agent calls submit_classification tool → structured JSON."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _mock_submit_classification(
            {
                "relevance_score": 5,
                "contextual_analysis": "Very important paper",
                "bottom_line": "Game changer",
                "suggested_js": {"id": "test-2026"},
                "suggested_filename": "Test_NEJM_2026.html",
                "relations": [],
            }
        )

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 5
        assert result["ai_analysis"] == "Very important paper"
        assert result["ai_parse_failed"] is False

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_research_then_classify(self, sample_candidate):
        """Agent uses research tool first, then submit_classification."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = _mock_submit_classification(
            {"relevance_score": 4, "contextual_analysis": "After research"},
            with_research_tool=True,
        )

        with patch("agent_tools.load_tracked_dois", return_value={}):
            result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 4
        assert mock_client.messages.create.call_count == 2

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_parse_failure_not_silent(self, sample_candidate):
        """If agent never calls submit_classification → parse_failed, NOT score 0."""
        mock_client = MagicMock()
        response = MagicMock()
        response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I think this paper is interesting but..."
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_parse_failed"] is True
        assert result["ai_score"] is None  # NOT 0

    def test_parse_failures_included_in_results(self):
        """Parse failures should be included in classify_all results (not dropped)."""
        papers = [
            {"title": "A", "topic": "mCRC-BRAF-V600E", "ai_score": 5, "ai_parse_failed": False},
            {"title": "B", "topic": "mCRC-BRAF-V600E", "ai_score": 2, "ai_parse_failed": False},
            {"title": "C", "topic": "mCRC-BRAF-V600E", "ai_score": None, "ai_parse_failed": True},
        ]
        # Simulate the filtering logic from classify_all
        from config import RELEVANCE_THRESHOLD

        kept = [
            c
            for c in papers
            if c.get("ai_parse_failed") or c.get("ai_score") is None or c["ai_score"] >= RELEVANCE_THRESHOLD
        ]
        assert len(kept) == 2  # score=5 + parse_failed, NOT score=2
        assert any(c["title"] == "C" for c in kept)  # parse failure kept
