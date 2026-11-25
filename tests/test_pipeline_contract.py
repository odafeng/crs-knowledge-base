"""Versioned migration contract; external providers are fixtures, real KB writes stay in tmp_path."""

import json
import socket
from copy import deepcopy
from datetime import date
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import classify
import config
import content_store
import main as pipeline
from accept_issue import accept
from create_issues import format_commentary_issue_body, format_issue_body
from publish import KB, PublishError, publish_commentary, publish_paper, unpublish
from validate import validate_data

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "pipeline-v1.json").read_text())
TODAY = FIXTURE["today"]


class FixtureDate(date):
    @classmethod
    def today(cls):
        return date.fromisoformat(TODAY)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    """Keep orchestration, triage, gates, writers, issue payloads and tracking real."""
    # The pipeline's JSON path, whichever writer the repository itself has now (postgres since cutover, #79).
    monkeypatch.setattr(content_store, "json_writer_active", lambda: True)
    kb = KB(tmp_path)
    kb.papers_json.parent.mkdir()
    kb.save(deepcopy(FIXTURE["kb"]))
    monkeypatch.setattr(config, "TRACKED_DOIS_FILE", tmp_path / "data/tracked-dois.json")
    monkeypatch.setattr(config, "TRACKED_ABSTRACTS_FILE", tmp_path / "data/tracked-abstracts.json")
    monkeypatch.delenv(config.CONTENT_DATABASE_ENV, raising=False)
    monkeypatch.setattr(config, "PAPERS_JSON", kb.papers_json)
    monkeypatch.setattr(pipeline, "date", FixtureDate)
    monkeypatch.setattr(pipeline, "publish_paper", partial(publish_paper, kb=kb))
    monkeypatch.setattr(pipeline, "publish_commentary", partial(publish_commentary, kb=kb))
    monkeypatch.setattr(pipeline.USAGE, "report", Mock())
    monkeypatch.setattr(pipeline.USAGE, "record", Mock())
    # Fail closed if a future refactor accidentally escapes the fixture boundaries.
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(pipeline, "repair_paper", Mock(return_value=False))
    for name in ("create_issues", "notify_papers"):
        monkeypatch.setattr(pipeline, name, Mock())
    return kb


def entries(kb):
    return {p["id"]: p for topic in kb.load().values() for p in topic.get("papers", [])}


def research_input(case):
    base = deepcopy(FIXTURE["research"])
    candidate = {**base["candidate"], **case.get("candidate", {})}
    classification = {**base["classification"], **case.get("classification", {})}
    if case.get("entry"):
        classification["ai_suggested_js"].update(case["entry"])
    return candidate, classification


def mock_research(monkeypatch, candidate, classification):
    monkeypatch.setattr(pipeline, "fetch_pubmed", Mock(return_value=[candidate]))
    # Include a duplicate feed record with a deliberately worse abstract.
    monkeypatch.setattr(pipeline, "fetch_rss", Mock(return_value=[{**candidate, "source": "rss", "abstract": ""}]))
    monkeypatch.setattr(classify, "ANTHROPIC_API_KEY", "fixture-only")
    monkeypatch.setattr(classify, "Anthropic", Mock())

    def classify_fixture(_client, paper, **_kwargs):
        paper.update(deepcopy(classification))
        return paper

    classifier = Mock(side_effect=classify_fixture)
    monkeypatch.setattr(classify, "classify_paper", classifier)
    return classifier


@pytest.mark.parametrize("case", FIXTURE["research_cases"], ids=lambda c: c["name"])
def test_research_migration_round_trip(harness, monkeypatch, case):
    kb = harness
    candidate, classification = research_input(case)
    classifier = mock_research(monkeypatch, candidate, classification)
    assert pipeline.run_pipeline() is False
    assert classifier.call_count == 1  # PubMed wins over duplicate RSS; Comment tag stays research.
    classified = classifier.call_args.args[1]
    assert classified["source"] == "pubmed"
    assert classified["abstract"] == candidate["abstract"]
    pipeline.create_issues.assert_not_called()

    tracked = config.load_tracked_dois()
    key = case.get("tracking_key", "10.9999/guthub-contract")
    if case.get("tracked", True):
        expected_tracking = {
            "topic": "mCRC-MSI-H",
            "added": TODAY,
            "score": classification["ai_score"],
            "pmid": "99999991",
        }
        assert tracked == {key: expected_tracking}
        assert config.load_tracked_abstracts() == {"test-abstract": expected_tracking}
        dois, pmids = config.tracked_ids(tracked)
        assert config.is_tracked({**candidate, "doi": "10.9999/doi-added-later"}, dois, pmids)
    else:
        assert tracked == config.load_tracked_abstracts() == {}

    if case["outcome"] == "filtered":
        assert len(entries(kb)) == 1
        assert not (kb.root / "docs").exists()
        pipeline.notify_papers.assert_not_called()
        return

    if case["outcome"] == "auto":
        assert pipeline.notify_papers.call_args.args[0] == [classified]
        assert classified["publish_status"] == "auto"
        saved = entries(kb)["contract-paper"]
        expected = {**deepcopy(FIXTURE["research"]["expected_entry"]), **case.get("entry", {})}
        expected["doi"] = candidate["doi"] or None
        assert saved == expected
        assert "AI 自動整理，未經人工審核" in (kb.root / saved["file"]).read_text()
        with pytest.raises(PublishError):
            publish_paper(classified, "auto", TODAY, kb)
        assert entries(kb)["contract-paper"] == saved
    else:
        assert len(entries(kb)) == 1
        assert not (kb.root / "docs").exists()
        pipeline.notify_papers.assert_not_called()
        assert classified["publish_status"] == "held"
        assert any(case["reason"] in reason for reason in classified["gate_reasons"])
        body = format_issue_body(classified)
        if not case.get("accept", True):
            with pytest.raises(PublishError, match="沒有可發布的資料"):
                accept(body, TODAY, kb)
            assert len(entries(kb)) == 1
            return
        accept(body, TODAY, kb)
        saved = entries(kb)["contract-paper"]
        assert saved["review"] == {"status": "accepted", "publishedAt": TODAY}
        assert saved["source"] == "secondary"
        assert "已經人工確認後發布" in (kb.root / saved["file"]).read_text()

    assert "<script>" not in (kb.root / saved["file"]).read_text()
    assert saved["relations"] == [{"targetId": "contract-target", "type": "builds_on"}]
    assert validate_data(kb.load(), kb.root) == []
    # Removal also clears dependent research links and AI news, preserving curated content.
    data = kb.load()
    data["mCRC-MSI-H"]["papers"][0]["relations"] = [{"targetId": "contract-paper", "type": "builds_on"}]
    kb.save(data)
    kb.news_json.write_text(json.dumps([{"id": "synthetic-news", "paperId": "contract-paper"}]))
    assert unpublish("contract-paper", kb) == "paper contract-paper"
    assert kb.load() == FIXTURE["kb"]
    assert not (kb.root / saved["file"]).exists()
    assert json.loads(kb.news_json.read_text()) == []
    with pytest.raises(PublishError, match="人工整理"):
        unpublish("contract-target", kb)


@pytest.mark.parametrize("case", FIXTURE["commentary_cases"], ids=lambda c: c["name"])
def test_commentary_migration_round_trip(harness, monkeypatch, case):
    kb = harness
    base = deepcopy(FIXTURE["commentary"])
    candidate = {**base["candidate"], **case.get("candidate", {})}
    result = {**base["model"], **case.get("model", {})}
    response = SimpleNamespace(
        stop_reason="refusal" if case.get("refusal") else "end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(result))],
    )
    client = Mock()
    client.beta.messages.create.return_value = response
    monkeypatch.setattr(pipeline, "ANTHROPIC_API_KEY", "fixture-only")
    monkeypatch.setattr(pipeline, "Anthropic", Mock(return_value=client))
    resolver = Mock(return_value=base["resolved_dois"])
    monkeypatch.setattr(pipeline, "resolve_dois", resolver)
    monkeypatch.setattr(pipeline, "fetch_pubmed", Mock(return_value=[candidate]))
    monkeypatch.setattr(pipeline, "fetch_rss", Mock(return_value=[]))
    held_capture: list = []
    real_pub_commentary = pipeline.publish_or_hold_commentary

    def capture_commentary(*args, **kwargs):
        out = real_pub_commentary(*args, **kwargs)
        held_capture.extend(out)
        return out

    monkeypatch.setattr(pipeline, "publish_or_hold_commentary", capture_commentary)
    assert pipeline.run_pipeline() is False
    client.beta.messages.create.assert_called_once()
    pipeline.create_issues.assert_not_called()
    pipeline.notify_papers.assert_not_called()
    held = held_capture
    tracked = config.load_tracked_dois()
    if case.get("tracked", True):
        assert tracked == {
            candidate["doi"]: {
                "topic": "mCRC-MSI-H",
                "added": TODAY,
                "kind": "commentary",
                "target": case.get("target", "contract-target"),
                "pmid": "99999992",
            }
        }
    else:
        assert tracked == {}

    if case["outcome"] in ("retry", "tracked-only"):
        assert held == [] and kb.load() == FIXTURE["kb"]
        return
    if case["outcome"] == "held":
        assert kb.load() == FIXTURE["kb"]
        assert len(held) == 1
        body = format_commentary_issue_body(held, TODAY)
        with pytest.raises(PublishError, match="沒有勾選"):
            accept(body, TODAY, kb)
        accept(body.replace("- [ ] [c0]", "- [x] [c0]"), TODAY, kb)
    else:
        assert held == []
        resolver.assert_called_once_with(["99999990"])

    saved = entries(kb)["contract-target"]["commentary"]
    assert len(saved) == 1
    assert saved[0]["summary"] == result["summary"]
    assert saved[0]["newData"] == result["has_new_data"]
    assert saved[0]["review"] == {"status": "accepted" if held else "auto", "publishedAt": TODAY}
    assert saved[0]["addedAt"] == TODAY
    publish_commentary([("contract-target", saved[0])], "accepted", TODAY, kb)
    assert entries(kb)["contract-target"]["commentary"] == saved  # Retry never duplicates or changes existing review.
    assert validate_data(kb.load(), kb.root) == []
    assert unpublish(candidate["doi"], kb).startswith("commentary ")
    assert kb.load() == FIXTURE["kb"]


def test_dry_run_never_changes_kb_or_tracking(harness, monkeypatch):
    candidate, classification = research_input({})
    mock_research(monkeypatch, candidate, classification)
    before = harness.papers_json.read_bytes()
    assert pipeline.run_pipeline(dry_run=True) is False
    assert harness.papers_json.read_bytes() == before
    assert not list((harness.root / "data").glob("tracked-*.json"))
    assert not (harness.root / "docs").exists()
    pipeline.create_issues.assert_not_called()
    pipeline.notify_papers.assert_not_called()
