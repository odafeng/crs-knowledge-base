"""Tests for agent tools."""

import json
from unittest.mock import MagicMock, patch

from agent_tools import AGENT_TOOLS, execute_tool, _parse_article_brief


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
        assert names == {"search_pubmed", "fetch_paper_details", "lookup_existing_papers", "web_fetch", "query_guidelines"}


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
    def test_web_fetch_strips_html(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html><body><p>Hello world</p></body></html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = execute_tool("web_fetch", {"url": "http://example.com"})
        assert "Hello world" in result
        assert "<html>" not in result


class TestQueryGuidelines:
    @patch("agent_tools.OE_COOKIES_JSON", "")
    @patch("agent_tools.OE_COOKIES_PATH")
    def test_returns_fallback_when_no_credentials(self, mock_path):
        mock_path.exists.return_value = False
        result = execute_tool("query_guidelines", {"question": "What is the standard for BRAF V600E mCRC?"})
        parsed = json.loads(result)
        assert "error" in parsed
        assert "not configured" in parsed["error"]
        assert "fallback" in parsed

    @patch("agent_tools._load_oe_cookies")
    @patch("agent_tools.urllib.request.urlopen")
    def test_returns_answer_on_success(self, mock_urlopen, mock_cookies):
        mock_cookies.return_value = [{"name": "session", "value": "abc123"}]

        # First call: submit question
        submit_resp = MagicMock()
        submit_resp.read.return_value = json.dumps({"id": "article-123"}).encode()
        submit_resp.__enter__ = lambda s: s
        submit_resp.__exit__ = MagicMock(return_value=False)

        # Second call: poll — completed
        poll_resp = MagicMock()
        poll_resp.read.return_value = json.dumps({
            "status": "completed",
            "content": "ASCO recommends encorafenib+cetuximab for BRAF V600E mCRC.",
            "citations": [{"title": "ASCO Guideline 2025", "journal": "JCO", "year": "2025"}],
        }).encode()
        poll_resp.__enter__ = lambda s: s
        poll_resp.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [submit_resp, poll_resp]

        result = execute_tool("query_guidelines", {"question": "BRAF V600E mCRC guideline"})
        parsed = json.loads(result)
        assert "answer" in parsed
        assert "encorafenib" in parsed["answer"]
        assert parsed["source"] == "openevidence"


class TestClassifyWithAgenticLoop:
    """Test the agentic loop in classify.py."""

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_agent_with_tool_use(self, sample_candidate):
        """Test that the agent loop handles tool_use → tool_result → end_turn."""
        from classify import classify_paper

        mock_client = MagicMock()

        # First response: agent wants to use a tool
        tool_response = MagicMock()
        tool_response.stop_reason = "tool_use"
        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "lookup_existing_papers"
        tool_use_block.input = {"topic": "mCRC-BRAF-V600E"}
        tool_use_block.id = "tool_123"
        tool_response.content = [tool_use_block]

        # Second response: agent gives final answer
        final_response = MagicMock()
        final_response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({
            "relevance_score": 4,
            "contextual_analysis": "Important paper after tool research",
            "bottom_line": "Key finding",
            "suggested_js": {"id": "test-2026"},
            "suggested_filename": "Test_2026.html",
            "relations": [],
        })
        final_response.content = [text_block]

        mock_client.messages.create.side_effect = [tool_response, final_response]

        with patch("agent_tools.load_tracked_dois", return_value={}):
            result = classify_paper(mock_client, sample_candidate)

        assert result["ai_score"] == 4
        assert "tool research" in result["ai_analysis"]
        # Verify two API calls were made (tool use + final)
        assert mock_client.messages.create.call_count == 2

    @patch("classify.ANTHROPIC_API_KEY", "test-key")
    def test_agent_direct_answer(self, sample_candidate):
        """Test agent that answers directly without tools."""
        from classify import classify_paper

        mock_client = MagicMock()
        response = MagicMock()
        response.stop_reason = "end_turn"
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = json.dumps({
            "relevance_score": 2,
            "contextual_analysis": "Low relevance paper",
        })
        response.content = [text_block]
        mock_client.messages.create.return_value = response

        result = classify_paper(mock_client, sample_candidate)
        assert result["ai_score"] == 2
        # Only one API call (no tool use)
        assert mock_client.messages.create.call_count == 1
