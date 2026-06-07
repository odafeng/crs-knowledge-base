"""Tests for main pipeline orchestration."""

from config import is_conference_season
from main import deduplicate_candidates


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


class TestPipelineContract:
    """Contract tests: verify the pipeline behaves as documented."""

    def test_no_auto_pr_import_in_main(self):
        """main.py must NOT import or call create_prs — all papers go to Issues."""
        import importlib

        source = importlib.util.find_spec("main").origin
        with open(source) as f:
            code = f.read()
        assert "create_prs" not in code, "main.py must not use create_prs — all papers go to Issues only"
        assert "from create_pr" not in code, "main.py must not import from create_pr"

    def test_score_4_goes_to_issues_not_pr(self):
        """Score 4 papers must result in Issues, never auto-PR/merge."""
        # This is a specification test: the pipeline's Layer 3 must be create_issues
        import inspect

        from main import run_pipeline

        source = inspect.getsource(run_pipeline)
        assert "create_issues" in source
        assert "create_prs" not in source


class TestIsConferenceSeason:
    """is_conference_season now lives in config.py; test it directly."""

    def test_conference_season_returns_tuple(self):
        result = is_conference_season()
        assert isinstance(result, tuple)
        assert len(result) == 2
        # First element is bool, second is str or None
        assert isinstance(result[0], bool)
        assert result[1] is None or isinstance(result[1], str)
