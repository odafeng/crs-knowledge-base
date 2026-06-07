"""Tests for RSS feed fetcher."""

from unittest.mock import patch

from fetch_rss import _extract_doi, _matches_topic, fetch_rss


class TestExtractDoi:
    def test_extracts_from_url(self):
        assert _extract_doi("https://doi.org/10.1056/NEJMoa1234567") == "10.1056/NEJMoa1234567"

    def test_extracts_from_text(self):
        text = "Published online: doi: 10.1038/s41591-024-03443-3. Available at..."
        assert _extract_doi(text) == "10.1038/s41591-024-03443-3"

    def test_returns_empty_for_no_doi(self):
        assert _extract_doi("No DOI here") == ""
        assert _extract_doi("") == ""
        assert _extract_doi(None) == ""


class TestMatchesTopic:
    def test_matches_case_insensitive(self):
        entry = {"title": "New BRAF V600E Trial Results", "description": ""}
        assert _matches_topic(entry, ["BRAF"]) is True

    def test_no_match(self):
        entry = {"title": "Lung Cancer Update", "description": "NSCLC treatment"}
        assert _matches_topic(entry, ["colorectal", "BRAF"]) is False

    def test_matches_in_description(self):
        entry = {"title": "New Trial", "description": "encorafenib in colorectal cancer"}
        assert _matches_topic(entry, ["colorectal"]) is True


class TestFetchRss:
    @patch("fetch_rss._fetch_feed", return_value=[])
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_returns_empty_when_no_entries(self, mock_queries, mock_tracked, mock_feed):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF"]},
            "rss_feeds": [{"name": "NEJM", "url": "http://example.com/rss"}],
        }
        results = fetch_rss()
        assert results == []

    @patch("fetch_rss._fetch_feed")
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_filters_by_topic_terms(self, mock_queries, mock_tracked, mock_feed):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF", "colorectal"]},
            "rss_feeds": [{"name": "NEJM", "url": "http://example.com/rss"}],
        }
        mock_feed.return_value = [
            {
                "title": "BRAF V600E colorectal cancer update",
                "description": "",
                "doi": "10.1056/test1",
                "link": "",
                "pub_date": "",
            },
            {
                "title": "Lung cancer immunotherapy",
                "description": "",
                "doi": "10.1056/test2",
                "link": "",
                "pub_date": "",
            },
        ]
        results = fetch_rss()
        assert len(results) == 1
        assert results[0]["doi"] == "10.1056/test1"
