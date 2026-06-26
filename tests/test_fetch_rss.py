"""Tests for journal feed fetcher (PubMed-backed)."""

from unittest.mock import patch

import pytest

from fetch_rss import AllFeedsFailedError, _assign_topic, _extract_doi, _journal_query, _matches_topic, fetch_rss


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
        entry = {"title": "New BRAF V600E Trial Results", "abstract": ""}
        assert _matches_topic(entry, ["BRAF"]) is True

    def test_no_match(self):
        entry = {"title": "Lung Cancer Update", "abstract": "NSCLC treatment"}
        assert _matches_topic(entry, ["colorectal", "BRAF"]) is False

    def test_matches_in_abstract(self):
        entry = {"title": "New Trial", "abstract": "encorafenib in colorectal cancer"}
        assert _matches_topic(entry, ["colorectal"]) is True


class TestJournalQuery:
    def test_scopes_to_journal_and_colorectal(self):
        q = _journal_query("N Engl J Med")
        assert '"N Engl J Med"[Journal]' in q
        assert "colorectal" in q.lower()


class TestAssignTopic:
    def test_assigns_first_matching_topic(self):
        topics_config = {
            "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF", "encorafenib"]},
            "mCRC-KRAS-G12C": {"rss_filter_terms": ["sotorasib"]},
        }
        art = {"title": "encorafenib in colorectal cancer", "abstract": ""}
        assert _assign_topic(art, topics_config) == "mCRC-BRAF-V600E"

    def test_returns_empty_when_no_match(self):
        topics_config = {"mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF"]}}
        art = {"title": "Pancreatic cancer trial", "abstract": ""}
        assert _assign_topic(art, topics_config) == ""


def _queries():
    return {
        "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF", "colorectal"]},
        "rss_feeds": [{"name": "NEJM", "pubmed_journal": "N Engl J Med"}],
    }


class TestFetchRss:
    @patch("fetch_rss.efetch", return_value=[])
    @patch("fetch_rss.esearch", return_value=[])
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_returns_empty_when_no_articles(self, mock_queries, mock_tracked, mock_esearch, mock_efetch):
        mock_queries.return_value = _queries()
        assert fetch_rss() == []

    @patch("fetch_rss.efetch")
    @patch("fetch_rss.esearch", return_value=["1", "2"])
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_filters_and_assigns_topic(self, mock_queries, mock_tracked, mock_esearch, mock_efetch):
        mock_queries.return_value = _queries()
        mock_efetch.return_value = [
            {"pmid": "1", "doi": "10.1056/test1", "title": "BRAF V600E colorectal cancer", "abstract": ""},
            {"pmid": "2", "doi": "10.1056/test2", "title": "Lung cancer immunotherapy", "abstract": ""},
        ]
        results = fetch_rss()
        assert len(results) == 1
        assert results[0]["doi"] == "10.1056/test1"
        assert results[0]["topic"] == "mCRC-BRAF-V600E"
        assert results[0]["source"] == "journal"

    @patch("fetch_rss.efetch")
    @patch("fetch_rss.esearch", return_value=["1"])
    @patch("fetch_rss.load_tracked_dois", return_value={"10.1056/test1": {"topic": "x"}})
    @patch("fetch_rss.load_queries")
    def test_skips_tracked_dois(self, mock_queries, mock_tracked, mock_esearch, mock_efetch):
        mock_queries.return_value = _queries()
        mock_efetch.return_value = [
            {"pmid": "1", "doi": "10.1056/test1", "title": "BRAF colorectal", "abstract": ""},
        ]
        assert fetch_rss() == []

    @patch("fetch_rss.esearch", side_effect=OSError("network down"))
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_raises_when_all_feeds_fail(self, mock_queries, mock_tracked, mock_esearch):
        mock_queries.return_value = _queries()
        with pytest.raises(AllFeedsFailedError):
            fetch_rss()

    @patch("fetch_rss.efetch", return_value=[])
    @patch("fetch_rss.esearch")
    @patch("fetch_rss.load_tracked_dois", return_value={})
    @patch("fetch_rss.load_queries")
    def test_partial_failure_does_not_raise(self, mock_queries, mock_tracked, mock_esearch, mock_efetch):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {"rss_filter_terms": ["BRAF"]},
            "rss_feeds": [
                {"name": "NEJM", "pubmed_journal": "N Engl J Med"},
                {"name": "JCO", "pubmed_journal": "J Clin Oncol"},
            ],
        }
        # First feed errors, second succeeds (empty) — should NOT raise.
        mock_esearch.side_effect = [OSError("boom"), []]
        assert fetch_rss() == []
