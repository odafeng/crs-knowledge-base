"""Tests for AI classification layer."""

import json
from unittest.mock import MagicMock, patch

from classify import (
    FALLBACK_BETA,
    MAX_AGENT_TURNS,
    RESCUE_OUTPUT_SCHEMA,
    SUBMIT_CLASSIFICATION_TOOL,
    can_repair,
    classify_all,
    classify_paper,
    repair_paper,
)
from config import CLASSIFY_MODEL


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


class TestClassifyPaper:
    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_structured_output_via_tool(self, sample_candidate):
        """Agent calls submit_classification tool → structured JSON."""
        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = _mock_submit_classification(
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
        mock_client.beta.messages.create.side_effect = _mock_submit_classification(
            {"relevance_score": 4, "contextual_analysis": "After research"},
            with_research_tool=True,
        )

        with patch("agent_tools.load_tracked_dois", return_value={}):
            result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 4
        assert mock_client.beta.messages.create.call_count == 2

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
        mock_client.beta.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_parse_failed"] is True
        assert result["ai_score"] is None  # NOT 0

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_rescue_recovers_from_turn_exhaustion(self, sample_candidate):
        """Agent researching until the turn budget runs out is rescued via structured output."""
        research = MagicMock()
        research.stop_reason = "tool_use"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "lookup_existing_papers"
        tool_block.input = {"topic": "mCRC-BRAF-V600E"}
        tool_block.id = "tool_1"
        research.content = [tool_block]

        forced = MagicMock()
        forced.stop_reason = "end_turn"
        thinking_block = MagicMock(type="thinking", thinking="")
        json_block = MagicMock(type="text")
        json_block.text = json.dumps(
            {
                "relevance_score": 3,
                "contextual_analysis": "Forced result",
                "bottom_line": "",
                "suggested_filename": "",
                "relations": [],
            }
        )
        forced.content = [thinking_block, json_block]

        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = [*[research] * MAX_AGENT_TURNS, forced]

        with patch("agent_tools.load_tracked_dois", return_value={}):
            result = classify_paper(mock_client, sample_candidate)

        assert result["ai_parse_failed"] is False
        assert result["ai_score"] == 3
        assert result["ai_analysis"] == "Forced result"
        final_kwargs = mock_client.beta.messages.create.call_args.kwargs
        # Forced tool_choice ("tool"/"any") is rejected by the model; tools are disabled
        # and the reply is constrained to the classification schema instead.
        assert final_kwargs["tool_choice"] == {"type": "none"}
        assert final_kwargs["output_config"]["format"] == {"type": "json_schema", "schema": RESCUE_OUTPUT_SCHEMA}
        # Same tools array and system prompt on every call, so earlier thinking blocks
        # stay valid and the cached prefix keeps matching.
        first_kwargs = mock_client.beta.messages.create.call_args_list[0].kwargs
        assert final_kwargs["tools"] == first_kwargs["tools"]
        assert final_kwargs["system"] == first_kwargs["system"]

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_refusal_goes_to_review_without_retry(self, sample_candidate):
        """A refusal (after server-side fallback) is routed to review, not resent."""
        response = MagicMock()
        response.stop_reason = "refusal"
        response.stop_details.category = "bio"
        response.content = []

        mock_client = MagicMock()
        mock_client.beta.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_parse_failed"] is True
        assert result["ai_score"] is None
        assert "bio" in result["ai_analysis"]
        assert mock_client.beta.messages.create.call_count == 1

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_request_uses_current_api_surface(self, sample_candidate):
        """No budget_tokens / forced tool_choice (both 400 on the current model)."""
        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = _mock_submit_classification(
            {"relevance_score": 2, "contextual_analysis": "Low"}
        )

        classify_paper(mock_client, sample_candidate)
        kwargs = mock_client.beta.messages.create.call_args.kwargs
        assert kwargs["model"] == CLASSIFY_MODEL
        assert kwargs["thinking"]["type"] == "adaptive"
        assert "budget_tokens" not in kwargs["thinking"]
        assert "effort" in kwargs["output_config"]
        assert kwargs.get("tool_choice", {"type": "auto"})["type"] in ("auto", "none")
        assert FALLBACK_BETA in kwargs["betas"]
        assert kwargs["fallbacks"] == "default"

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_forced_submit_failure_falls_back_to_parse_failed(self, sample_candidate):
        """If even the forced submission fails, the paper still goes to review."""
        response = MagicMock()
        response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Still thinking..."
        response.content = [text_block]

        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = [*[response] * MAX_AGENT_TURNS, RuntimeError("API down")]

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_parse_failed"] is True
        assert result["ai_score"] is None

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

    def test_score_three_passes_the_auto_publish_threshold(self):
        """Moderate (score 3) papers auto-publish too; score 2 is still dropped (K14 #308, ADR-0032)."""
        from config import RELEVANCE_THRESHOLD

        assert 3 >= RELEVANCE_THRESHOLD > 2


def _assert_strict_objects(schema: dict, path: str = "$") -> None:
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, f"{path} needs additionalProperties: false"
        for key, sub in schema.get("properties", {}).items():
            _assert_strict_objects(sub, f"{path}.{key}")
    if schema.get("type") == "array":
        _assert_strict_objects(schema["items"], f"{path}[]")


def test_rescue_schema_is_structured_output_compatible():
    """Structured outputs require additionalProperties: false on every object."""
    _assert_strict_objects(RESCUE_OUTPUT_SCHEMA)
    assert set(RESCUE_OUTPUT_SCHEMA["required"]) == set(RESCUE_OUTPUT_SCHEMA["properties"])


class TestRepairPaper:
    """ADR-0029: bounded AI self-repair against verbatim PubMed abstracts."""

    def test_can_repair_rejects_unrepairable_cases(self, sample_candidate):
        topics = {"mCRC-BRAF-V600E"}
        assert can_repair({**sample_candidate, "abstract_status": "full"}, topics) is True
        assert can_repair({**sample_candidate, "abstract_status": "truncated"}, topics) is False
        assert can_repair({**sample_candidate, "abstract_status": "missing"}, topics) is False
        assert can_repair({**sample_candidate, "abstract_status": "full", "ai_parse_failed": True}, topics) is False
        assert can_repair({**sample_candidate, "abstract_status": "full", "topic": "unknown"}, topics) is False

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_repair_paper_applies_submission_with_submit_tool_only(self, sample_candidate):
        paper = {**sample_candidate, "ai_score": 4, "ai_suggested_js": {"id": "old", "n": 999}}
        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = _mock_submit_classification(
            {
                "relevance_score": 4,
                "contextual_analysis": "Repaired analysis",
                "bottom_line": "Repaired line",
                "suggested_js": {"id": "fixed-2026", "n": 200},
                "suggested_filename": "Fixed_2026.html",
                "evidence": [{"claim": "n=200", "source": "abstract", "quote": "200 patients", "url": None}],
            }
        )
        assert repair_paper(mock_client, paper, ["KB 條目中這些數字在摘要裡找不到：999"]) is True
        assert paper["ai_suggested_js"]["id"] == "fixed-2026"
        assert paper["ai_suggested_js"]["n"] == 200
        # Research tools must be disabled during repair so only the verbatim abstract can be cited.
        assert mock_client.beta.messages.create.call_args.kwargs["tools"] == [SUBMIT_CLASSIFICATION_TOOL]

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_repair_paper_nudges_once_on_end_turn(self, sample_candidate):
        end = MagicMock(stop_reason="end_turn", content=[MagicMock(type="text", text="Let me fix it")])
        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = [
            end,
            *_mock_submit_classification({"relevance_score": 4, "contextual_analysis": "ok", "evidence": []}),
        ]
        assert repair_paper(mock_client, dict(sample_candidate), ["沒有數字出處"]) is True
        assert mock_client.beta.messages.create.call_count == 2

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_repair_paper_handles_api_error_gracefully(self, sample_candidate):
        mock_client = MagicMock()
        mock_client.beta.messages.create.side_effect = RuntimeError("timeout")
        assert repair_paper(mock_client, dict(sample_candidate), ["沒有數字出處"]) is False
