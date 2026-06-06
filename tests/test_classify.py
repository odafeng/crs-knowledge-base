"""Tests for AI classification layer."""

import json
from unittest.mock import MagicMock, patch

from classify import classify_all, classify_paper


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


class TestClassifyPaper:
    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_parses_json_response(self, sample_candidate):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text=json.dumps({
                "relevance_score": 5,
                "contextual_analysis": "Very important paper",
                "bottom_line": "Game changer",
                "suggested_js": {"id": "test-2026"},
                "suggested_filename": "Test_NEJM_2026.html",
                "relations": [],
            }))]
        )

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 5
        assert result["ai_analysis"] == "Very important paper"
        assert result["ai_bottom_line"] == "Game changer"

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_handles_markdown_wrapped_json(self, sample_candidate):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text='Here is my analysis:\n```json\n{"relevance_score": 3, "contextual_analysis": "Moderate"}\n```')]
        )

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 3

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_handles_malformed_response(self, sample_candidate):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="This is not JSON at all, just plain text analysis.")]
        )

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 0  # fallback
