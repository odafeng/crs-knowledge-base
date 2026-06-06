"""Tests for GitHub Issue creation."""

from create_issues import _topic_to_label, format_issue_body


class TestTopicToLabel:
    def test_all_topics_have_labels(self):
        topics = [
            "mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H",
            "mCRC-HER2", "mCRC-RAS-wt", "robotic-surgery",
        ]
        for t in topics:
            label = _topic_to_label(t)
            assert label, f"No label for {t}"
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
        body = format_issue_body(sample_candidate)
        assert "**Topic**" in body
        assert "Suggested JS Object" not in body
