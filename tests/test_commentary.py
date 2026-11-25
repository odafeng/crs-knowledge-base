"""Tests for commentary triage (editorials, letters, comments, news)."""

import json
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

from commentary import (
    CommentaryProposal,
    apply_commentary,
    commentary_type,
    kb_papers,
    match_by_comment_on,
    split_commentary,
    triage_commentary,
)
from config import PAPERS_JSON
from fetch_pubmed import _parse_article
from validate import validate_data

STELLAR_DOI = "10.1016/S0140-6736(25)02025-2"
STELLAR_PMID = "41130252"


@pytest.fixture
def kb():
    return kb_papers(json.loads(PAPERS_JSON.read_text()))


@pytest.fixture
def editorial():
    """Shaped like issue #6: the Med editorial on STELLAR-303."""
    return {
        "pmid": "41519113",
        "doi": "10.1016/j.medj.2025.100957",
        "title": "STELLAR-303: Breaking the immunotherapy wall in MSS colorectal cancer.",
        "journal": "Med",
        "year": "2026",
        "abstract": "The phase 3 STELLAR-303 trial demonstrated a significant overall survival benefit...",
        "publication_types": ["Editorial", "Comment"],
        "comment_on_pmids": [STELLAR_PMID],
        "topic": "generic-CRS",
    }


def _structured_response(payload: dict, stop_reason: str = "end_turn") -> MagicMock:
    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [MagicMock(type="thinking", thinking=""), MagicMock(type="text", text=json.dumps(payload))]
    return response


class TestParsePublicationTypes:
    def test_parses_types_and_comment_on(self):
        xml = """<PubmedArticle><MedlineCitation><PMID>41519113</PMID>
          <Article><ArticleTitle>STELLAR-303 editorial</ArticleTitle><Journal><Title>Med</Title></Journal>
            <PublicationTypeList><PublicationType UI="D016421">Editorial</PublicationType>
              <PublicationType UI="D016420">Comment</PublicationType></PublicationTypeList></Article>
          <CommentsCorrectionsList>
            <CommentsCorrections RefType="CommentOn"><RefSource>Lancet. 2025</RefSource><PMID>41130252</PMID></CommentsCorrections>
            <CommentsCorrections RefType="Cites"><PMID>11111111</PMID></CommentsCorrections>
          </CommentsCorrectionsList></MedlineCitation></PubmedArticle>"""
        result = _parse_article(ET.fromstring(xml))
        assert result["publication_types"] == ["Editorial", "Comment"]
        assert result["comment_on_pmids"] == [STELLAR_PMID]

    def test_research_article_has_no_comment_on(self, sample_pubmed_xml):
        article = ET.fromstring(sample_pubmed_xml).find(".//PubmedArticle")
        result = _parse_article(article)
        assert result["publication_types"] == []
        assert result["comment_on_pmids"] == []


class TestCommentaryType:
    @pytest.mark.parametrize(
        ("types", "expected"),
        [
            (["Editorial"], "Editorial"),
            (["Letter", "Comment"], "Letter"),  # most specific wins
            (["Comment"], "Comment"),
            (["News"], "News"),
            (["Journal Article"], None),
            (["Randomized Controlled Trial", "Comment"], None),  # original research tagged Comment
            (["Meta-Analysis", "Letter"], None),
            ([], None),
        ],
    )
    def test_types(self, types, expected):
        assert commentary_type({"publication_types": types}) == expected

    def test_split(self, editorial, sample_candidate):
        research, commentary = split_commentary([sample_candidate, editorial])
        assert research == [sample_candidate]
        assert commentary == [editorial]


class TestMatching:
    def test_comment_on_matches_existing_trial(self, editorial, kb):
        target = match_by_comment_on(editorial, kb, lambda pmids: {STELLAR_PMID: STELLAR_DOI})
        assert target == "STELLAR303_Lancet_2025"

    def test_comment_on_doi_match_is_case_insensitive(self, editorial, kb):
        target = match_by_comment_on(editorial, kb, lambda pmids: {STELLAR_PMID: STELLAR_DOI.lower()})
        assert target == "STELLAR303_Lancet_2025"

    def test_comment_on_unknown_trial(self, editorial, kb):
        assert match_by_comment_on(editorial, kb, lambda pmids: {STELLAR_PMID: "10.9999/other"}) is None

    def test_no_comment_on_skips_lookup(self, editorial, kb):
        editorial["comment_on_pmids"] = []
        resolver = MagicMock()
        assert match_by_comment_on(editorial, kb, resolver) is None
        resolver.assert_not_called()


class TestTriage:
    def test_comment_on_overrides_model_target(self, editorial, kb):
        client = MagicMock()
        client.beta.messages.create.return_value = _structured_response(
            {"target_id": "kn177", "summary": "評論", "has_substantive_critique": False, "has_new_data": False}
        )
        proposal = triage_commentary(client, editorial, kb, lambda pmids: {STELLAR_PMID: STELLAR_DOI})
        assert proposal.target_id == "STELLAR303_Lancet_2025"
        assert proposal.match_method == "comment_on"
        assert proposal.type == "Editorial"
        assert proposal.year == 2026

    def test_ai_maps_to_existing_trial(self, editorial, kb):
        editorial["comment_on_pmids"] = []
        client = MagicMock()
        client.beta.messages.create.return_value = _structured_response(
            {
                "target_id": "STELLAR303_Lancet_2025",
                "summary": "首個 MSS 免疫治療 Phase 3 OS 獲益",
                "has_substantive_critique": True,
                "has_new_data": False,
            }
        )
        proposal = triage_commentary(client, editorial, kb, MagicMock())
        assert proposal.target_id == "STELLAR303_Lancet_2025"
        assert proposal.match_method == "ai"
        assert proposal.critique is True

        kwargs = client.beta.messages.create.call_args.kwargs
        schema = kwargs["output_config"]["format"]["schema"]
        allowed = schema["properties"]["target_id"]["anyOf"][0]["enum"]
        assert "STELLAR303_Lancet_2025" in allowed  # model can only pick real KB ids
        assert "tools" not in kwargs  # lightweight: no agent tools

    def test_kb_list_is_the_cached_prefix(self, editorial, kb):
        """The stable part (instructions + KB list) sits in system with a cache breakpoint;
        the article itself only appears after it, so later calls in a run hit the cache."""
        client = MagicMock()
        client.beta.messages.create.return_value = _structured_response(
            {"target_id": None, "summary": "x", "has_substantive_critique": False, "has_new_data": False}
        )
        triage_commentary(client, editorial, kb, lambda pmids: {STELLAR_PMID: STELLAR_DOI})
        kwargs = client.beta.messages.create.call_args.kwargs
        (system,) = kwargs["system"]
        assert system["cache_control"] == {"type": "ephemeral"}
        assert "STELLAR303_Lancet_2025" in system["text"]
        assert editorial["title"] not in system["text"]
        user = kwargs["messages"][0]["content"]
        assert editorial["title"] in user
        assert "STELLAR303_Lancet_2025" in user  # the CommentOn hint stays per-article

    def test_unmapped(self, editorial, kb):
        editorial["comment_on_pmids"] = []
        client = MagicMock()
        client.beta.messages.create.return_value = _structured_response(
            {"target_id": None, "summary": "泛論", "has_substantive_critique": False, "has_new_data": False}
        )
        proposal = triage_commentary(client, editorial, kb, MagicMock())
        assert proposal.target_id is None
        assert proposal.match_method is None

    def test_refusal_returns_none(self, editorial, kb):
        client = MagicMock()
        client.beta.messages.create.return_value = _structured_response({}, stop_reason="refusal")
        assert triage_commentary(client, editorial, kb, lambda pmids: {}) is None


def _proposal(target_id: str | None = "STELLAR303_Lancet_2025") -> CommentaryProposal:
    return CommentaryProposal(
        target_id=target_id,
        doi="10.1016/j.medj.2025.100957",
        pmid="41519113",
        title="STELLAR-303: Breaking the immunotherapy wall",
        journal="Med",
        year=2026,
        type="Editorial",
        summary="評論",
        critique=False,
        new_data=True,
        match_method="comment_on",
    )


class TestApplyCommentary:
    def test_adds_entry_once(self):
        data = {"generic-CRS": {"papers": [{"id": "STELLAR303_Lancet_2025"}]}}
        entry = _proposal().to_entry("2026-11-15")
        assert apply_commentary(data, [("STELLAR303_Lancet_2025", entry)]) == ["STELLAR303_Lancet_2025"]
        assert apply_commentary(data, [("STELLAR303_Lancet_2025", entry)]) == []
        assert data["generic-CRS"]["papers"][0]["commentary"] == [entry]

    def test_entry_passes_validation(self):
        data = json.loads(PAPERS_JSON.read_text())
        data["generic-CRS"]["papers"][0]["commentary"] = []
        apply_commentary(data, [("STELLAR303_Lancet_2025", _proposal().to_entry("2026-11-15"))])
        assert validate_data(data) == []


class TestValidateCommentary:
    def _data(self, commentary: list[dict]) -> dict:
        return {
            "t": {
                "papers": [
                    {
                        "id": "p1",
                        "year": 2025,
                        "journal": "Lancet",
                        "studyType": "Phase 3 RCT",
                        "regimen": "A vs B",
                        "endpoint": "OS",
                        "result": "x",
                        "bottomLine": "y",
                        "doi": "10.1/p1",
                        "relations": [],
                        "commentary": commentary,
                    }
                ]
            }
        }

    def test_rejects_bad_entries(self):
        bad = {"doi": "10.1/p1", "title": "t", "journal": "j", "type": "Review", "summary": "", "addedAt": "11/15"}
        errors = validate_data(self._data([bad]))
        joined = "\n".join(errors)
        assert "unknown type" in joined
        assert "empty field: summary" in joined
        assert "boolean critique" in joined
        assert "YYYY-MM-DD" in joined
        assert "duplicates paper" in joined  # commentary DOI equals the paper's own DOI

    def test_rejects_duplicate_commentary(self):
        entry = _proposal().to_entry("2026-11-15")
        errors = validate_data(self._data([entry, dict(entry)]))
        assert any("duplicates commentary" in e for e in errors)


class TestPipelineRouting:
    """Commentary never reaches full classification or review issues (ADR-0029)."""

    def _run(self, candidates, proposal):
        with (
            patch("main.fetch_pubmed", return_value=candidates),
            patch("main.fetch_rss", return_value=[]),
            patch("main.ANTHROPIC_API_KEY", "test-key"),
            patch("main.Anthropic"),
            patch("main.triage_commentary", return_value=proposal) as triage,
            patch("main.classify_all", return_value=[]) as classify,
            patch("main.create_issues") as create_issues,
            patch("main.publish_commentary") as publish_comm,
            patch("main.notify_papers"),
            patch("main.load_tracked_dois", return_value={}),
            patch("main.load_tracked_abstracts", return_value={}),
            patch("main.save_tracked_dois") as save_dois,
            patch("main.save_tracked_abstracts"),
        ):
            from main import run_pipeline

            run_pipeline()
        return triage, classify, create_issues, publish_comm, save_dois

    def test_unverified_mapped_commentary_is_skipped_and_tracked(self, editorial):
        proposal = _proposal()
        triage, classify, create_issues, publish_comm, save_dois = self._run([editorial], proposal)
        assert triage.call_count == 1
        assert classify.call_args.args[0] == []  # not sent to the full agent
        create_issues.assert_not_called()
        publish_comm.assert_not_called()  # AI-only match does not auto-publish
        tracked = save_dois.call_args.args[0]
        assert tracked[editorial["doi"]]["kind"] == "commentary"
        assert tracked[editorial["doi"]]["target"] == "STELLAR303_Lancet_2025"

    def test_unmapped_commentary_only_tracked(self, editorial):
        before = PAPERS_JSON.read_text()
        _, classify, create_issues, publish_comm, save_dois = self._run([editorial], _proposal(target_id=None))
        publish_comm.assert_not_called()
        create_issues.assert_not_called()
        assert classify.call_args.args[0] == []
        tracked = save_dois.call_args.args[0]
        assert tracked[editorial["doi"]] == {
            "topic": "generic-CRS",
            "added": tracked[editorial["doi"]]["added"],
            "pmid": editorial["pmid"],
            "kind": "commentary",
            "target": None,
        }
        assert PAPERS_JSON.read_text() == before

    def test_low_score_research_is_tracked(self, sample_candidate):
        def classify(research, dry_run=False):
            research[0]["ai_score"] = 2
            research[0]["ai_parse_failed"] = False
            return []

        sample_candidate["publication_types"] = ["Journal Article"]
        with (
            patch("main.fetch_pubmed", return_value=[sample_candidate]),
            patch("main.fetch_rss", return_value=[]),
            patch("main.classify_all", side_effect=classify),
            patch("main.create_issues") as create_issues,
            patch("main.notify_papers"),
            patch("main.load_tracked_dois", return_value={}),
            patch("main.load_tracked_abstracts", return_value={}),
            patch("main.save_tracked_dois") as save_dois,
            patch("main.save_tracked_abstracts"),
        ):
            from main import run_pipeline

            run_pipeline()
        create_issues.assert_not_called()
        assert save_dois.call_args.args[0][sample_candidate["doi"]]["score"] == 2
