"""Tests for gated auto-publishing, accepted-issue publishing and unpublishing (ADR-0013)."""

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

import content_store
from accept_issue import accept
from commentary import CommentaryProposal
from create_issues import format_commentary_issue_body, format_issue_body
from publish import KB, PublishError, mark_reviewed, publish_commentary, publish_paper, unpublish, unpublish_story
from validate import validate_data

ROOT = Path(__file__).resolve().parent.parent
TODAY = "2026-11-15"

ABSTRACT = (
    "BACKGROUND: Test background. METHODS: In this phase 2 trial, 56 patients were treated. "
    "RESULTS: The major pathological response rate was 36% (95% CI 12.8-64.9). "
    "CONCLUSIONS: Promising <b>activity</b>."
)


@pytest.fixture
def kb(tmp_path) -> KB:
    (tmp_path / "data").mkdir()
    shutil.copy(ROOT / "data" / "papers.json", tmp_path / "data" / "papers.json")
    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    return KB(root=tmp_path)


def _paper(**js_overrides) -> dict:
    js = {
        "id": "test-auto-2026",
        "year": 2026,
        "journal": "Nat Med",
        "studyType": "Phase 2",
        "n": 56,
        "regimen": "Drug A <script>alert('x')</script>",
        "endpoint": "pMR",
        "result": "pMR 36%",
        "bottomLine": "pMR 36%",
        "relations": [{"targetId": "niche2", "type": "builds_on"}, {"targetId": "made-up", "type": "builds_on"}],
    }
    js.update(js_overrides)
    return {
        "topic": "mCRC-MSI-H",
        "title": "Test trial <i>title</i>",
        "doi": "10.9999/test-auto",
        "pmid": "99999999",
        "journal": "Nat Med",
        "year": "2026",
        "abstract": ABSTRACT,
        "abstract_status": "full",
        "ai_score": 4,
        "ai_parse_failed": False,
        "ai_analysis": "分析",
        "ai_bottom_line": "pMR 36%",
        "ai_suggested_js": js,
        "ai_suggested_filename": "Test_NatMed_2026.html",
        "ai_evidence": [
            {"claim": "n=56", "source": "abstract", "quote": "56 patients were treated", "url": None},
            {"claim": "pMR 36%", "source": "abstract", "quote": "response rate was 36%", "url": None},
        ],
    }


def _entry(kb: KB, paper_id: str) -> dict | None:
    return next((p for t in kb.load().values() for p in t.get("papers", []) if p["id"] == paper_id), None)


class TestPublishPaper:
    def test_writes_entry_and_detail_source(self, kb):
        entry = publish_paper(_paper(), "auto", TODAY, kb)

        saved = _entry(kb, "test-auto-2026")
        assert saved == entry
        assert saved["review"] == {"status": "auto", "publishedAt": TODAY}
        assert saved["file"] == "docs/mCRC-MSI-H/Test_NatMed_2026.html"
        assert saved["relations"] == [{"targetId": "niche2", "type": "builds_on"}]  # unknown target dropped
        assert saved["regimen"] == "Drug A"  # tags stripped at write time; plain text stored unescaped (K6 #256)

        page = (kb.root / saved["file"]).read_text()
        assert "AI 自動整理，未經人工審核" in page
        assert "<script>" not in page and "<i>title</i>" not in page
        assert "✓ 摘要中找到" in page

        assert validate_data(kb.load(), kb.root) == []

    def test_accepted_banner(self, kb):
        entry = publish_paper(_paper(), "accepted", TODAY, kb)
        assert "已經人工確認" in (kb.root / entry["file"]).read_text()

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"id": "../../etc/passwd"}, "不合法的 id"),
            ({"id": "kn177"}, "Duplicate id"),
            ({"studyType": "Case report"}, "unknown studyType"),
        ],
    )
    def test_invalid_entry_leaves_kb_untouched(self, kb, overrides, message):
        before = kb.papers_json.read_text()
        with pytest.raises(PublishError) as exc:
            publish_paper(_paper(**overrides), "auto", TODAY, kb)
        assert any(message in r for r in exc.value.reasons)
        assert kb.papers_json.read_text() == before
        assert not (kb.root / "docs" / "mCRC-MSI-H" / "Test_NatMed_2026.html").exists()

    def test_unsafe_filename_falls_back_to_id(self, kb):
        paper = _paper()
        paper["ai_suggested_filename"] = "../index.html"
        assert publish_paper(paper, "auto", TODAY, kb)["file"] == "docs/mCRC-MSI-H/test-auto-2026.html"

    def test_robotic_topic_publishes(self, kb):
        paper = _paper(id="real-tme-2026")
        paper["topic"] = "robotic-surgery"
        paper["ai_suggested_filename"] = "REAL_TME_2026.html"
        entry = publish_paper(paper, "auto", TODAY, kb)
        assert entry["file"] == "docs/robotic-surgery/REAL_TME_2026.html"
        assert (kb.root / entry["file"]).exists()
        assert any(p["id"] == "real-tme-2026" for p in kb.load()["robotic-surgery"]["papers"])
        assert validate_data(kb.load(), kb.root) == []

    def test_unknown_topic_refused(self, kb):
        paper = _paper()
        paper["topic"] = "nonexistent-topic"
        with pytest.raises(PublishError):
            publish_paper(paper, "auto", TODAY, kb)


class TestUnpublish:
    def test_removes_published_paper(self, kb):
        entry = publish_paper(_paper(), "auto", TODAY, kb)
        assert unpublish("test-auto-2026", kb) == "paper test-auto-2026"
        assert _entry(kb, "test-auto-2026") is None
        assert not (kb.root / entry["file"]).exists()
        assert validate_data(kb.load(), kb.root) == []

    def test_refuses_hand_curated_entry(self, kb):
        with pytest.raises(PublishError, match="人工整理"):
            unpublish("kn177", kb)
        assert _entry(kb, "kn177") is not None

    def test_unknown_target(self, kb):
        with pytest.raises(PublishError, match="找不到"):
            unpublish("nope", kb)

    def test_commentary_round_trip(self, kb):
        entry = _proposal().to_entry(TODAY)
        publish_commentary([("kn177", entry)], "auto", TODAY, kb)
        saved = _entry(kb, "kn177")["commentary"][0]
        assert saved["review"]["status"] == "auto"
        assert validate_data(kb.load(), kb.root) == []
        assert unpublish(entry["doi"], kb).startswith("commentary")
        assert "commentary" not in _entry(kb, "kn177")


def _proposal(index_doi: str = "10.9999/comment") -> CommentaryProposal:
    return CommentaryProposal(
        target_id="kn177",
        doi=index_doi,
        pmid="",
        title="Letter on KEYNOTE-177",
        journal="J Clin Oncol",
        year=2026,
        type="Letter",
        summary="質疑 crossover 對 OS 的影響",
        critique=True,
        new_data=False,
        match_method="ai",
    )


class TestAccept:
    def test_held_paper_issue_publishes_as_accepted(self, kb):
        paper = _paper(n=51)
        paper["gate_reasons"] = ["KB 條目中這些數字在摘要裡找不到：51"]
        summary = accept(format_issue_body(paper), TODAY, kb)
        assert summary == "publish test-auto-2026 (docs/mCRC-MSI-H/Test_NatMed_2026.html)"
        assert _entry(kb, "test-auto-2026")["review"]["status"] == "accepted"

    def test_commentary_issue_publishes_only_checked(self, kb):
        proposals = [_proposal("10.9999/a"), _proposal("10.9999/b")]
        body = format_commentary_issue_body(proposals, TODAY).replace("- [ ] [c1]", "- [x] [c1]")
        accept(body, TODAY, kb)
        dois = [c["doi"] for c in _entry(kb, "kn177")["commentary"]]
        assert dois == ["10.9999/b"]

    def test_commentary_issue_with_nothing_checked(self, kb):
        with pytest.raises(PublishError, match="沒有勾選"):
            accept(format_commentary_issue_body([_proposal()], TODAY), TODAY, kb)

    def test_old_format_issue(self, kb):
        with pytest.raises(PublishError, match="沒有可發布的資料"):
            accept("## AI Contextual Analysis\nno payload here", TODAY, kb)


class TestPipelineGate:
    """The pipeline publishes only gate-passing papers; everything else becomes an issue."""

    @pytest.fixture(autouse=True)
    def json_writer(self, monkeypatch):
        # The pipeline's JSON path, whichever writer the repository itself has now (postgres since cutover, #79).
        monkeypatch.setattr(content_store, "json_writer_active", lambda: True)

    def test_publish_or_hold(self):
        from main import publish_or_hold

        good = _paper()
        bad = _paper(n=51, id="other-2026")
        bad["doi"] = "10.9999/other"
        with patch("main.publish_paper", return_value={"id": "x", "file": "f"}) as publish:
            published, held = publish_or_hold([good, bad], TODAY, dry_run=False)
        assert published == [good] and held == [bad]
        assert publish.call_count == 1
        assert publish.call_args.args[0] is good
        assert good["publish_status"] == "auto"
        assert any("51" in r for r in bad["gate_reasons"])

    def test_publish_error_holds_paper(self):
        from main import publish_or_hold

        paper = _paper()
        with patch("main.publish_paper", side_effect=PublishError(["Duplicate id"])):
            published, held = publish_or_hold([paper], TODAY, dry_run=False)
        assert published == [] and held == [paper]
        assert paper["gate_reasons"] == ["Duplicate id"]

    def test_dry_run_publishes_nothing(self):
        from main import publish_or_hold

        with patch("main.publish_paper") as publish:
            publish_or_hold([_paper()], TODAY, dry_run=True)
        publish.assert_not_called()


class TestWorkflowContract:
    """No workflow may merge PRs; the accept workflow only reacts to `accepted` on bot issues."""

    def test_no_workflow_merges_or_bypasses_review(self):
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text()
            assert "pr merge" not in text and "--admin" not in text, wf.name

    def test_accept_workflow_condition(self):
        text = (ROOT / ".github" / "workflows" / "paper-accept.yml").read_text()
        assert "github.event.label.name == 'accepted'" in text
        assert "github.event.issue.user.type == 'Bot'" in text

    def test_kb_writers_share_concurrency_group(self):
        for name in ("paper-watch.yml", "paper-accept.yml", "unpublish.yml"):
            assert "group: kb-main-writes" in (ROOT / ".github" / "workflows" / name).read_text(), name

    def test_unpublish_inputs_not_interpolated_in_shell(self):
        text = (ROOT / ".github" / "workflows" / "unpublish.yml").read_text()
        run_lines = [line for line in text.splitlines() if "run:" in line or line.startswith("          ")]
        assert not any("${{ inputs." in line for line in run_lines)


def test_payload_is_valid_json_for_accept():
    """The embedded payload survives a model string containing '-->'."""
    paper = _paper()
    paper["ai_analysis"] = "tricky --> end of comment"
    body = format_issue_body(paper)
    from issue_data import extract

    assert extract(body, "paper")["ai_analysis"] == "tricky --> end of comment"
    json.dumps(extract(body, "paper"))


class TestReviewFindings:
    """Findings from the Codex review of #35."""

    def test_fallback_bottom_line_is_gated(self):
        from main import publish_or_hold

        paper = _paper(bottomLine="")
        paper["ai_bottom_line"] = "OS 999 months"
        with patch("main.publish_paper") as publish:
            published, held = publish_or_hold([paper], TODAY, dry_run=False)
        publish.assert_not_called()
        assert published == [] and held == [paper]
        assert any("999" in r for r in paper["gate_reasons"])

    def test_numbers_in_regimen_and_endpoint_are_gated(self):
        from provenance import evaluate_paper_gate

        paper = _paper(endpoint="pMR at 12 weeks")
        result = evaluate_paper_gate(paper, {"mCRC-MSI-H"})
        assert any("12" in r for r in result.reasons)

    def test_unpublish_drops_cross_topic_relations_and_card_refs(self, kb):
        publish_paper(_paper(), "auto", TODAY, kb)
        data = kb.load()
        data["generic-CRS"]["papers"][0]["relations"].append({"targetId": "test-auto-2026", "type": "builds_on"})
        data["mCRC-MSI-H"]["standard_of_care"]["cards"][0]["refs"].append("test-auto-2026")
        kb.save(data)

        unpublish("test-auto-2026", kb)
        after = kb.load()
        assert all(r["targetId"] != "test-auto-2026" for r in after["generic-CRS"]["papers"][0]["relations"])
        assert "test-auto-2026" not in after["mCRC-MSI-H"]["standard_of_care"]["cards"][0]["refs"]
        assert validate_data(after, kb.root) == []

    def test_declined_commentary_is_left_for_retry(self):
        from main import update_tracking

        commentary = {"doi": "10.9999/refused", "topic": "generic-CRS", "title": "x"}
        with (
            patch("main.load_tracked_dois", return_value={}),
            patch("main.load_tracked_abstracts", return_value={}),
            patch("main.save_tracked_dois") as save,
            patch("main.save_tracked_abstracts"),
        ):
            update_tracking([], [(commentary, None)], TODAY)
        assert "10.9999/refused" not in save.call_args.args[0]

    def test_accepted_paper_keeps_secondary_source(self, kb):
        """Codex review of #49: an accepted paper must not be labelled as abstract-verified."""
        paper = _paper()
        paper["ai_evidence"].append(
            {"claim": "ORR 40%", "source": "web_fetch", "quote": "40%", "url": "https://example.org"}
        )
        assert publish_paper(paper, "accepted", TODAY, kb)["source"] == "secondary"

    def test_auto_published_paper_is_abstract_sourced(self, kb):
        assert publish_paper(_paper(), "auto", TODAY, kb)["source"] == "abstract"


class TestReview:
    """E6 #159: an admin marks an auto-published entry reviewed, or takes one story down."""

    def test_auto_paper_becomes_accepted_with_its_banner(self, kb):
        publish_paper(_paper(), "auto", TODAY, kb)
        assert mark_reviewed("paper", "test-auto-2026", kb) == "review paper test-auto-2026"
        entry = _entry(kb, "test-auto-2026")
        assert entry["review"] == {"status": "accepted", "publishedAt": TODAY}
        page = (kb.root / entry["file"]).read_text()
        assert "未經人工審核" not in page and "已經人工確認" in page

    def test_hand_curated_and_reviewed_entries_are_refused(self, kb):
        with pytest.raises(PublishError, match="人工整理"):
            mark_reviewed("paper", "kn177", kb)
        publish_paper(_paper(), "accepted", TODAY, kb)
        with pytest.raises(PublishError, match="已經審過"):
            mark_reviewed("paper", "test-auto-2026", kb)

    def test_one_story_is_unpublished_and_its_paper_stays(self, kb):
        shutil.copy(ROOT / "data" / "news.json", kb.news_json)
        story = json.loads(kb.news_json.read_text())[0]
        assert unpublish_story(story["id"], kb) == f"news {story['id']}"
        assert story["id"] not in {s["id"] for s in json.loads(kb.news_json.read_text())}
        assert any(p["id"] == story["paperId"] for t in kb.load().values() for p in t.get("papers", []))
        with pytest.raises(PublishError, match="找不到消息"):
            mark_reviewed("news", story["id"], kb)
