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

    def test_layer_3_is_gate_then_issues(self):
        """ADR-0013: papers publish only through the provenance gate; the rest become issues. Never PRs."""
        import inspect

        from main import publish_or_hold, run_pipeline

        pipeline = inspect.getsource(run_pipeline)
        assert "publish_or_hold" in pipeline
        assert "create_issues(held" in pipeline
        assert "create_prs" not in pipeline

        gate = inspect.getsource(publish_or_hold)
        assert "evaluate_paper_gate" in gate
        assert '"auto"' in gate  # pipeline-published entries are always marked unreviewed


class TestIsConferenceSeason:
    """is_conference_season now lives in config.py; test it directly."""

    def test_conference_season_returns_tuple(self):
        result = is_conference_season()
        assert isinstance(result, tuple)
        assert len(result) == 2
        # First element is bool, second is str or None
        assert isinstance(result[0], bool)
        assert result[1] is None or isinstance(result[1], str)


class TestPubmedReach:
    """A paper stays without MeSH for weeks after it appears; a [MeSH]-only query never sees it (OSERO, J3 #210)."""

    def test_every_topic_query_reads_title_and_abstract_too(self):
        import json

        from config import QUERIES_FILE

        queries = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
        for topic, q in queries.items():
            if not isinstance(q, dict) or "pubmed_query" not in q:
                continue
            assert "[tiab]" in q["pubmed_query"], f"{topic} relies on MeSH alone"

    def test_reldate_widens_the_pubmed_window(self):
        from unittest.mock import patch

        with (
            patch("main.fetch_pubmed", return_value=[]) as fetch,
            patch("main.fetch_rss", return_value=[]),
            patch("main.load_tracked_dois", return_value={}),
            patch("main.load_tracked_abstracts", return_value={}),
        ):
            from main import run_pipeline

            run_pipeline(topic="generic-CRS", dry_run=True, reldate=60)
        assert fetch.call_args.kwargs["reldate"] == 60


REQUESTED = {"pmid": "42811047", "title": "OSERO", "abstract": "Regorafenib then FTD/TPI.", "doi": "10.1/x"}


class TestReviewRequested:
    """A tracked paper can be sent to review again: its issue failed to open, or it scored low (J5 #214)."""

    def _classify(self, papers, dry_run=False):
        for p in papers:
            p.update(ai_score=3, ai_analysis="", ai_parse_failed=False, ai_suggested_js={"id": "osero"})
        return []  # below the threshold, so the scan would drop it

    def test_a_low_scoring_paper_still_gets_a_review_issue(self):
        from unittest.mock import patch

        with (
            patch("main.efetch", return_value=[dict(REQUESTED)]),
            patch("main.classify_all", side_effect=self._classify),
            patch("main.create_issues") as issues,
            patch("main.update_tracking") as tracking,
            patch("main.publish_paper") as publish,
        ):
            from main import review_requested

            review_requested(["42811047"], "generic-CRS")

        (held,) = issues.call_args.args
        assert [p["pmid"] for p in held] == ["42811047"]
        assert held[0]["topic"] == "generic-CRS"
        assert held[0]["gate_reasons"][0] == "維護者指定送審（AI 評分 3/5）"
        tracking.assert_called_once()
        publish.assert_not_called()

    def test_dry_run_neither_tracks_nor_opens_issues_for_real(self):
        from unittest.mock import patch

        with (
            patch("main.efetch", return_value=[dict(REQUESTED)]),
            patch("main.classify_all", side_effect=self._classify),
            patch("main.create_issues") as issues,
            patch("main.update_tracking") as tracking,
        ):
            from main import review_requested

            review_requested(["42811047"], "generic-CRS", dry_run=True)

        assert issues.call_args.kwargs["dry_run"] is True
        tracking.assert_not_called()

    def test_the_agent_is_told_to_draft_an_entry_whatever_the_score(self):
        from topic_agents import build_paper_prompt

        assert "維護者已指定" in build_paper_prompt({**REQUESTED, "maintainer_requested": True})
        assert "維護者已指定" not in build_paper_prompt(REQUESTED)

    def test_review_needs_a_topic(self, monkeypatch):
        import pytest

        import main

        monkeypatch.setattr("sys.argv", ["main.py", "--review", "42811047"])
        with pytest.raises(SystemExit):
            main.main()
