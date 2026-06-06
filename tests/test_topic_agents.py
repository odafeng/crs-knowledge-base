"""Tests for topic agent prompt generation."""

from topic_agents import build_paper_prompt, build_system_prompt, _extract_papers_from_html


class TestBuildSystemPrompt:
    def test_contains_topic_context(self):
        prompt = build_system_prompt("mCRC-BRAF-V600E")
        assert "BRAF V600E" in prompt
        assert "BEACON" in prompt
        assert "BREAKWATER" in prompt

    def test_contains_existing_papers(self):
        prompt = build_system_prompt("mCRC-BRAF-V600E")
        assert "beacon-2019" in prompt
        assert "10.1056/NEJMoa1908075" in prompt

    def test_contains_scoring_rubric(self):
        prompt = build_system_prompt("mCRC-BRAF-V600E")
        assert "Relevance Score" in prompt
        assert "Practice-changing" in prompt

    def test_all_topics_have_prompts(self):
        topics = [
            "mCRC-BRAF-V600E", "mCRC-KRAS-G12C", "mCRC-MSI-H",
            "mCRC-HER2", "mCRC-RAS-wt", "robotic-surgery",
        ]
        for topic in topics:
            prompt = build_system_prompt(topic)
            assert len(prompt) > 500, f"Prompt too short for {topic}"

    def test_unknown_topic_still_works(self):
        prompt = build_system_prompt("unknown-topic")
        assert "Relevance Score" in prompt


class TestBuildPaperPrompt:
    def test_includes_all_fields(self, sample_candidate):
        prompt = build_paper_prompt(sample_candidate)
        assert "BRAF V600E" in prompt
        assert "Smith J" in prompt
        assert "N Engl J Med" in prompt
        assert "10.1056/NEJMoa9999999" in prompt
        assert "encorafenib" in prompt


class TestExtractPapersFromHtml:
    def test_extracts_all_topic_arrays(self):
        papers = _extract_papers_from_html()
        expected_topics = {"mCRC-BRAF-V600E", "mCRC-RAS-wt", "mCRC-KRAS-G12C", "mCRC-MSI-H", "mCRC-HER2"}
        assert set(papers.keys()) == expected_topics

    def test_braf_contains_beacon(self):
        papers = _extract_papers_from_html()
        assert "beacon-2019" in papers["mCRC-BRAF-V600E"]
