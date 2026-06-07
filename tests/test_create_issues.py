"""Tests for GitHub Issue creation."""

from create_issues import _topic_to_label, format_issue_body
from topics import Topic


class TestTopicToLabel:
    def test_all_topics_have_labels(self):
        for t in Topic:
            label = _topic_to_label(t.value)
            assert label, f"No label for {t.value}"
            assert label.startswith("topic:")

    def test_unknown_topic(self):
        assert _topic_to_label("unknown") == ""


class TestFormatIssueBody:
    def test_contains_key_sections(self, sample_classified_paper):
        body = format_issue_body(sample_classified_paper)
        assert "**Topic**" in body
        assert "**Relevance Score**: 5/5" in body
        assert "AI Contextual Analysis" in body
        assert "Suggested JS Object" in body
        assert "Suggested Filename" in body

    def test_contains_doi_link(self, sample_classified_paper):
        body = format_issue_body(sample_classified_paper)
        assert "doi.org/10.1056/NEJMoa9999999" in body

    def test_collapses_abstract(self, sample_classified_paper):
        body = format_issue_body(sample_classified_paper)
        assert "<details>" in body
        assert "Original Abstract" in body

    def test_handles_no_ai_results(self, sample_candidate):
        sample_candidate["ai_score"] = None
        sample_candidate["ai_analysis"] = "(skipped)"
        sample_candidate["ai_parse_failed"] = False
        body = format_issue_body(sample_candidate)
        assert "**Topic**" in body
        assert "Suggested JS Object" not in body

    def test_parse_failure_shows_warning(self, sample_candidate):
        sample_candidate["ai_score"] = None
        sample_candidate["ai_analysis"] = "(parse failed)"
        sample_candidate["ai_parse_failed"] = True
        body = format_issue_body(sample_candidate)
        assert "Warning" in body
        assert "Manual review" in body
