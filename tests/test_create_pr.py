"""Tests for auto-PR creation."""

import json
from unittest.mock import MagicMock, patch

from create_pr import TOPIC_CONFIG, insert_js_object, apply_chart_updates, _placeholder_html


class TestTopicConfig:
    def test_all_topics_have_config(self):
        topics = [
            "mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H",
            "mCRC-HER2", "mCRC-RAS-wt", "robotic-surgery",
        ]
        for t in topics:
            assert t in TOPIC_CONFIG, f"Missing config for {t}"

    def test_docs_dir_set(self):
        for topic, config in TOPIC_CONFIG.items():
            assert config["docs_dir"], f"No docs_dir for {topic}"


class TestPlaceholderHtml:
    def test_contains_basic_structure(self, sample_candidate):
        html = _placeholder_html(sample_candidate)
        assert "<!DOCTYPE html>" in html
        assert sample_candidate["title"] in html
        assert sample_candidate["doi"] in html
        assert sample_candidate["authors"] in html


class TestInsertJsObject:
    @patch("create_pr.INDEX_HTML")
    def test_inserts_into_braf_array(self, mock_index):
        mock_index.read_text.return_value = """
const BRAF_PAPERS = [
  { id: 'beacon-2019', year: 2019 },
];
"""
        js_obj = {"id": "test-2026", "year": 2026}

        insert_js_object("mCRC-BRAF-V600E", js_obj)

        written = mock_index.write_text.call_args[0][0]
        assert '"test-2026"' in written
        assert "2026" in written
        # Original entry still present
        assert "beacon-2019" in written

    @patch("create_pr.INDEX_HTML")
    def test_returns_false_for_unknown_topic(self, mock_index):
        result = insert_js_object("unknown-topic", {"id": "test"})
        assert result is False

    @patch("create_pr.INDEX_HTML")
    def test_returns_false_for_robotic(self, mock_index):
        # robotic-surgery has no JS array (var is None)
        result = insert_js_object("robotic-surgery", {"id": "test"})
        assert result is False


class TestApplyChartUpdates:
    @patch("create_pr.INDEX_HTML")
    def test_add_bar(self, mock_index):
        mock_index.read_text.return_value = """
const METRICS = {
  mOS: {
    label: 'mOS', max: 35,
    bars: [
      { label:'EC', val:9.3, hr:'0.61', color:'#3182ce' }
    ]
  }
};"""
        updates = {
            "mOS": {
                "action": "add",
                "bar": {"label": "NewArm", "val": 25.0, "hr": "0.55", "color": "#38a169"},
            }
        }
        result = apply_chart_updates("mCRC-BRAF-V600E", updates)
        assert result is True
        written = mock_index.write_text.call_args[0][0]
        assert "NewArm" in written
        assert "25.0" in written

    @patch("create_pr.INDEX_HTML")
    def test_update_max(self, mock_index):
        mock_index.read_text.return_value = """
const METRICS = {
  mOS: {
    label: 'mOS', max: 35,
    bars: [
      { label:'EC', val:9.3, hr:'0.61', color:'#3182ce' }
    ]
  }
};"""
        updates = {
            "mOS": {
                "action": "add",
                "bar": {"label": "New", "val": 40.0, "hr": "0.5", "color": "#38a169"},
                "new_max": 45,
            }
        }
        apply_chart_updates("mCRC-BRAF-V600E", updates)
        written = mock_index.write_text.call_args[0][0]
        assert "45" in written

    def test_returns_false_for_no_metrics(self):
        result = apply_chart_updates("mCRC-HER2", {"mOS": {"action": "add", "bar": {}}})
        assert result is False
