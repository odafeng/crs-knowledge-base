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

    def test_layer_3_auto_repairs_and_opens_no_review_issues(self):
        """ADR-0013 + ADR-0029: papers publish only through the provenance gate (with bounded self-repair); no routine issues or PRs."""
        import inspect

        from main import publish_or_hold, run_pipeline

        pipeline = inspect.getsource(run_pipeline)
        assert "publish_or_hold" in pipeline
        assert "create_issues(" not in pipeline
        assert "create_digest_issue(" not in pipeline
        assert "create_commentary_review_issue(" not in pipeline
        assert "create_prs" not in pipeline

        gate = inspect.getsource(publish_or_hold)
        assert "evaluate_paper_gate" in gate
        assert "repair_paper" in gate
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


DIGEST = {"number": 7, "body": "", "author": {"login": "owner"}}


class TestReviewPicks:
    """Papers ticked on an accepted digest go through the --review path (J6 #218)."""

    def _run(self, picks, review=None, digests=None, dry_run=False):
        from unittest.mock import patch

        with (
            patch("main.accepted_digests", return_value=[DIGEST] if digests is None else digests),
            patch("main.picked", return_value=picks),
            patch("main.review_requested", side_effect=review or (lambda pmids, topic, dry_run: len(pmids))) as rr,
            patch("main.finish") as finish,
        ):
            from main import review_picks

            ok = review_picks(dry_run=dry_run)
        return ok, rr, finish

    def test_picks_are_reviewed_by_topic_and_the_digest_is_closed(self):
        ok, rr, finish = self._run({"generic-CRS": ["1", "3"], "mCRC-RAS-wt": ["2"]})
        assert ok
        assert [c.args for c in rr.call_args_list] == [(["1", "3"], "generic-CRS"), (["2"], "mCRC-RAS-wt")]
        finish.assert_called_once_with(7, 3, 3)

    def test_nothing_ticked_still_reports_back(self):
        ok, rr, finish = self._run({})
        assert ok
        rr.assert_not_called()
        finish.assert_called_once_with(7, 0, 0)

    def test_a_failure_leaves_the_digest_for_the_next_run(self):
        def boom(pmids, topic, dry_run):
            raise RuntimeError("credit")

        ok, _, finish = self._run({"generic-CRS": ["1"]}, review=boom)
        assert not ok
        finish.assert_not_called()

    def test_dry_run_touches_no_issue(self):
        ok, rr, finish = self._run({"generic-CRS": ["1"]}, dry_run=True)
        assert ok
        assert rr.call_args.kwargs["dry_run"] is True
        finish.assert_not_called()

    def test_listing_failure_is_reported(self):
        from unittest.mock import patch

        with patch("main.accepted_digests", return_value=None):
            from main import review_picks

            assert review_picks() is False


def test_pipeline_opens_no_issues_for_score_three_or_unpublishable_papers():
    from unittest.mock import patch

    research = [
        {"pmid": "1", "title": "score 3 paper", "topic": "generic-CRS", "abstract": "Full abstract text."},
        {"pmid": "2", "title": "score 2 paper", "topic": "generic-CRS", "abstract": "Full abstract text."},
        {"pmid": "3", "title": "unpublishable score 4", "topic": "generic-CRS", "abstract": ""},
    ]

    def classify(papers, dry_run=False):
        scores = (3, 2, 4)
        for p, score in zip(papers, scores, strict=True):
            p.update(ai_score=score, ai_parse_failed=False, ai_suggested_js={}, ai_evidence=[])
        return [papers[2]]

    with (
        patch("main.fetch_pubmed", return_value=research),
        patch("main.fetch_rss", return_value=[]),
        patch("main.classify_all", side_effect=classify),
        patch("main.create_issues") as issues,
        patch("main.notify_papers") as notify,
        patch("main.update_tracking") as tracking,
        patch("main.USAGE"),
    ):
        from main import run_pipeline

        run_pipeline()
    issues.assert_not_called()
    notify.assert_not_called()
    tracking.assert_called_once()
