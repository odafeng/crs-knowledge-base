"""Tests for auto-PR creation."""

import json
from unittest.mock import patch

from create_pr import _placeholder_html, apply_chart_updates, insert_js_object
from topics import TOPIC_DOCS_DIR, TOPIC_JS_VAR, TOPIC_METRICS_VAR, Topic


class TestTopicConfig:
    def test_all_topics_have_docs_dir(self):
        for t in Topic:
            assert t in TOPIC_DOCS_DIR, f"No docs_dir for {t.value}"

    def test_all_topics_in_js_var(self):
        for t in Topic:
            assert t in TOPIC_JS_VAR, f"Missing from TOPIC_JS_VAR: {t.value}"

    def test_all_topics_in_metrics_var(self):
        for t in Topic:
            assert t in TOPIC_METRICS_VAR, f"Missing from TOPIC_METRICS_VAR: {t.value}"


class TestPlaceholderHtml:
    def test_contains_basic_structure(self, sample_candidate):
        html = _placeholder_html(sample_candidate)
        assert "<!DOCTYPE html>" in html
        assert sample_candidate["title"] in html
        assert sample_candidate["doi"] in html
        assert sample_candidate["authors"] in html


class TestInsertJsObject:
    def test_inserts_into_json(self, tmp_path):
        papers_file = tmp_path / "papers.json"
        papers_file.write_text(
            json.dumps(
                {
                    "mCRC-BRAF-V600E": {"papers": [{"id": "beacon-2019"}], "metrics": None},
                }
            )
        )

        with patch("create_pr.PAPERS_JSON", papers_file):
            result = insert_js_object("mCRC-BRAF-V600E", {"id": "test-2026", "year": 2026})

        assert result is True
        data = json.loads(papers_file.read_text())
        ids = [p["id"] for p in data["mCRC-BRAF-V600E"]["papers"]]
        assert "beacon-2019" in ids
        assert "test-2026" in ids

    def test_returns_false_for_unknown_topic(self, tmp_path):
        papers_file = tmp_path / "papers.json"
        papers_file.write_text(json.dumps({"mCRC-BRAF-V600E": {"papers": []}}))

        with patch("create_pr.PAPERS_JSON", papers_file):
            result = insert_js_object("unknown-topic", {"id": "test"})
        assert result is False


class TestApplyChartUpdates:
    def test_add_bar(self, tmp_path):
        papers_file = tmp_path / "papers.json"
        papers_file.write_text(
            json.dumps(
                {
                    "mCRC-BRAF-V600E": {
                        "papers": [],
                        "metrics": {
                            "mOS": {
                                "label": "mOS",
                                "max": 35,
                                "bars": [{"label": "EC", "val": 9.3, "hr": "0.61", "color": "#3182ce"}],
                            }
                        },
                    }
                }
            )
        )

        with patch("create_pr.PAPERS_JSON", papers_file):
            result = apply_chart_updates(
                "mCRC-BRAF-V600E", {"mOS": {"action": "add", "bar": {"label": "NewArm", "val": 25.0}}}
            )

        assert result is True
        data = json.loads(papers_file.read_text())
        bars = data["mCRC-BRAF-V600E"]["metrics"]["mOS"]["bars"]
        assert len(bars) == 2
        assert bars[1]["label"] == "NewArm"

    def test_update_max(self, tmp_path):
        papers_file = tmp_path / "papers.json"
        papers_file.write_text(
            json.dumps({"mCRC-BRAF-V600E": {"papers": [], "metrics": {"mOS": {"label": "mOS", "max": 35, "bars": []}}}})
        )

        with patch("create_pr.PAPERS_JSON", papers_file):
            apply_chart_updates(
                "mCRC-BRAF-V600E", {"mOS": {"action": "add", "bar": {"label": "X", "val": 40}, "new_max": 45}}
            )

        data = json.loads(papers_file.read_text())
        assert data["mCRC-BRAF-V600E"]["metrics"]["mOS"]["max"] == 45

    def test_returns_false_for_no_metrics(self, tmp_path):
        papers_file = tmp_path / "papers.json"
        papers_file.write_text(json.dumps({"mCRC-HER2": {"papers": [], "metrics": None}}))

        with patch("create_pr.PAPERS_JSON", papers_file):
            result = apply_chart_updates("mCRC-HER2", {"mOS": {"action": "add", "bar": {}}})
        assert result is False
