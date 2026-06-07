"""Tests for agent tools."""

import json
from unittest.mock import MagicMock, patch

from agent_tools import AGENT_TOOLS, execute_tool


class TestToolDefinitions:
    def test_all_tools_have_required_fields(self):
        for tool in AGENT_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool
            assert tool["input_schema"]["type"] == "object"

    def test_tool_count(self):
        assert len(AGENT_TOOLS) == 5

    def test_tool_names(self):
        names = {t["name"] for t in AGENT_TOOLS}
        assert names == {
            "search_pubmed",
            "fetch_paper_details",
            "lookup_existing_papers",
            "web_fetch",
            "query_guidelines",
        }


class TestExecuteTool:
    def test_unknown_tool(self):
        result = execute_tool("nonexistent_tool", {})
        parsed = json.loads(result)
        assert "error" in parsed

    @patch("agent_tools.load_tracked_dois")
    def test_lookup_existing(self, mock_tracked):
        mock_tracked.return_value = {
            "10.1056/test": {"topic": "mCRC-BRAF-V600E", "added": "2026-01-01"},
        }
        result = execute_tool("lookup_existing_papers", {"topic": "mCRC-BRAF-V600E"})
        parsed = json.loads(result)
        assert parsed["tracked_count"] == 1
        assert "existing_papers_js" in parsed

    @patch("agent_tools.urllib.request.urlopen")
    def test_web_fetch_with_real_content(self, mock_urlopen):
        # Provide enough content for trafilatura/readability to extract
        html = b"""<html><head><title>Test Page</title></head><body>
        <article><h1>Study Results</h1>
        <p>This phase 3 randomized trial evaluated encorafenib plus cetuximab
        versus standard chemotherapy in patients with BRAF V600E mutant metastatic
        colorectal cancer. The primary endpoint was overall survival.</p>
        <p>Results showed significant improvement in median OS (30.3 vs 15.1 months).</p>
        </article></body></html>"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = html
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = execute_tool("web_fetch", {"url": "http://example.com"})
        parsed = json.loads(result)
        # Should extract via trafilatura or readability
        assert "text" in parsed or "warning" in parsed
        if "text" in parsed:
            assert "encorafenib" in parsed["text"] or "phase 3" in parsed["text"].lower()

    @patch("agent_tools.urllib.request.urlopen")
    def test_web_fetch_warns_on_empty_content(self, mock_urlopen):
        # Minimal HTML — extractors can't get meaningful text
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body></body></html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = execute_tool("web_fetch", {"url": "http://example.com"})
        parsed = json.loads(result)
        assert "warning" in parsed


class TestQueryGuidelines:
    @patch("agent_tools._tool_search_pubmed")
    def test_finds_guideline_via_pubmed(self, mock_pubmed):
        mock_pubmed.return_value = json.dumps(
            {
                "results": [{"title": "NCCN CRC Guideline 2026", "pmid": "99999"}],
                "count": 1,
            }
        )
        result = execute_tool("query_guidelines", {"question": "BRAF V600E mCRC guideline"})
        parsed = json.loads(result)
        assert parsed["source"] == "pubmed_guideline_search"
        assert len(parsed["results"]) > 0

    @patch("agent_tools._tool_search_pubmed", side_effect=Exception("fail"))
    def test_fallback_when_pubmed_fails(self, mock_pubmed):
        result = execute_tool("query_guidelines", {"question": "unknown guideline"})
        parsed = json.loads(result)
        assert "fallback" in parsed


class TestClassifyWithAgenticLoop:
    """Test the agentic loop with submit_classification tool."""

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_agent_with_tool_use_then_submit(self, sample_candidate):
        """research tool → submit_classification."""
        from classify import classify_paper

        mock_client = MagicMock()

        # First response: research tool
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "lookup_existing_papers"
        tool_block.input = {"topic": "mCRC-BRAF-V600E"}
        tool_block.id = "tool_123"
        tool_response.content = [tool_block]

        # Second response: submit_classification
        final_response = MagicMock()
        final_response.stop_reason = "tool_use"
        submit_block = MagicMock()
        submit_block.type = "tool_use"
        submit_block.name = "submit_classification"
        submit_block.input = {
            "relevance_score": 4,
            "contextual_analysis": "Important paper after tool research",
        }
        submit_block.id = "submit_1"
        final_response.content = [submit_block]

        mock_client.messages.create.side_effect = [tool_response, final_response]

        with patch("agent_tools.load_tracked_dois", return_value={}):
            result = classify_paper(mock_client, sample_candidate)

        assert result["ai_score"] == 4
        assert result["ai_parse_failed"] is False
        assert mock_client.messages.create.call_count == 2

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_agent_direct_submit(self, sample_candidate):
        """Agent calls submit_classification directly (no research needed)."""
        from classify import classify_paper

        mock_client = MagicMock()
        response = MagicMock()
        response.stop_reason = "tool_use"
        submit_block = MagicMock()
        submit_block.type = "tool_use"
        submit_block.name = "submit_classification"
        submit_block.input = {"relevance_score": 2, "contextual_analysis": "Low relevance"}
        submit_block.id = "submit_1"
        response.content = [submit_block]
        mock_client.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 2
        assert mock_client.messages.create.call_count == 1

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_no_submit_marks_parse_failure(self, sample_candidate):
        """Agent that never calls submit_classification → parse_failed."""
        from classify import classify_paper

        mock_client = MagicMock()
        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [MagicMock(type="text", text="Just some text")]
        mock_client.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_parse_failed"] is True
        assert result["ai_score"] is None
