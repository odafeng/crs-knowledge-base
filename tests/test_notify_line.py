"""Tests for LINE notification."""

from unittest.mock import MagicMock, patch

from notify_line import _format_paper_message, format_digest, send_line


class TestFormatPaperMessage:
    def test_score_5_shows_practice_changing(self, sample_classified_paper):
        msg = _format_paper_message(sample_classified_paper)
        assert "Practice-Changing" in msg
        assert "Score 5/5" in msg
        assert "Auto-PR" in msg

    def test_score_4_shows_high_impact(self, sample_candidate):
        sample_candidate["ai_score"] = 4
        sample_candidate["ai_bottom_line"] = "Important finding"
        msg = _format_paper_message(sample_candidate)
        assert "High-Impact" in msg
        assert "Score 4/5" in msg
        assert "GitHub Issue" in msg

    def test_includes_doi_link(self, sample_classified_paper):
        msg = _format_paper_message(sample_classified_paper)
        assert "doi.org/10.1056/NEJMoa9999999" in msg


class TestFormatDigest:
    def test_empty_returns_empty(self):
        assert format_digest([]) == ""

    def test_includes_header_and_counts(self, sample_classified_paper):
        msg = format_digest([sample_classified_paper])
        assert "Paper Watch" in msg
        assert "Practice-changing: 1" in msg

    def test_truncates_long_message(self, sample_classified_paper):
        papers = [sample_classified_paper] * 50
        msg = format_digest(papers)
        assert len(msg) <= 5000


class TestSendLine:
    @patch("notify_line.LINE_CHANNEL_ACCESS_TOKEN", "")
    @patch("notify_line.LINE_USER_ID", "")
    def test_skips_when_no_credentials(self):
        result = send_line("test")
        assert result is False

    @patch("notify_line.LINE_USER_ID", "U1234")
    @patch("notify_line.LINE_CHANNEL_ACCESS_TOKEN", "token123")
    @patch("notify_line.urllib.request.urlopen")
    def test_sends_successfully(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = send_line("test message")
        assert result is True
        mock_urlopen.assert_called_once()
