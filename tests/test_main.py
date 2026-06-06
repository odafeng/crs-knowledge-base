"""Tests for main pipeline orchestration."""

from unittest.mock import patch

from main import deduplicate_candidates, is_conference_season


class TestDeduplicateCandidates:
    def test_removes_duplicate_dois(self):
        candidates = [
            {"doi": "10.1056/test1", "title": "A", "source": "pubmed"},
            {"doi": "10.1056/test1", "title": "A (RSS)", "source": "rss"},
            {"doi": "10.1056/test2", "title": "B", "source": "pubmed"},
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 2

    def test_prefers_pubmed_over_rss(self):
        candidates = [
            {"doi": "10.1056/test1", "title": "RSS version", "source": "rss"},
            {"doi": "10.1056/test1", "title": "PubMed version", "source": "pubmed"},
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 1
        assert result[0]["title"] == "PubMed version"

    def test_handles_empty_list(self):
        assert deduplicate_candidates([]) == []

    def test_handles_no_doi(self):
        candidates = [
            {"doi": "", "title": "No DOI paper", "source": "asco", "pmid": "", "abstract_id": "asco-123"},
            {"doi": "", "title": "Another", "source": "esmo", "pmid": "", "abstract_id": "esmo-456"},
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 2


class TestIsConferenceSeason:
    @patch("main.date")
    def test_asco_season(self, mock_date):
        mock_date.today.return_value.strftime.return_value = "06-01"
        in_season, name = is_conference_season()
        assert in_season is True
        assert "ASCO" in name

    @patch("main.date")
    def test_not_in_season(self, mock_date):
        mock_date.today.return_value.strftime.return_value = "03-15"
        in_season, _ = is_conference_season()
        assert in_season is False
