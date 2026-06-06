"""Tests for PubMed fetcher."""

import json
from unittest.mock import MagicMock, patch

import pytest

from fetch_pubmed import _parse_article, efetch, esearch, fetch_pubmed
import xml.etree.ElementTree as ET


class TestParseArticle:
    """Unit tests for XML article parsing."""

    def test_parses_basic_fields(self, sample_pubmed_xml):
        root = ET.fromstring(sample_pubmed_xml)
        article = root.find(".//PubmedArticle")
        result = _parse_article(article)

        assert result["pmid"] == "12345678"
        assert result["doi"] == "10.1056/NEJMoa9999999"
        assert result["journal"] == "N Engl J Med"
        assert result["year"] == "2026"
        assert "BRAF V600E" in result["title"]
        assert "Smith J" in result["authors"]
        assert "Doe A" in result["authors"]
        assert "encorafenib" in result["abstract"]

    def test_handles_missing_doi(self, sample_pubmed_xml):
        xml = sample_pubmed_xml.replace(b'IdType="doi"', b'IdType="pubmed"')
        root = ET.fromstring(xml)
        article = root.find(".//PubmedArticle")
        result = _parse_article(article)
        assert result["doi"] == ""

    def test_truncates_long_author_list(self, sample_pubmed_xml):
        extra_authors = b"""
            <Author><LastName>A</LastName><Initials>B</Initials></Author>
            <Author><LastName>C</LastName><Initials>D</Initials></Author>
            <Author><LastName>E</LastName><Initials>F</Initials></Author>
        """
        xml = sample_pubmed_xml.replace(
            b"</AuthorList>", extra_authors + b"</AuthorList>"
        )
        root = ET.fromstring(xml)
        article = root.find(".//PubmedArticle")
        result = _parse_article(article)
        assert "et al." in result["authors"]


class TestFetchPubmed:
    """Integration-level tests for fetch_pubmed (with mocked HTTP)."""

    @patch("fetch_pubmed.esearch", return_value=["12345678"])
    @patch("fetch_pubmed.efetch")
    @patch("fetch_pubmed.load_tracked_dois", return_value={})
    @patch("fetch_pubmed.load_queries")
    def test_returns_new_candidates(self, mock_queries, mock_tracked, mock_efetch, mock_esearch):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {
                "pubmed_query": "test query",
            }
        }
        mock_efetch.return_value = [{
            "pmid": "12345678",
            "doi": "10.1056/NEJMoa9999999",
            "title": "Test",
            "authors": "Smith J",
            "journal": "NEJM",
            "year": "2026",
            "abstract": "Test abstract",
        }]

        results = fetch_pubmed(topic="mCRC-BRAF-V600E")
        assert len(results) == 1
        assert results[0]["topic"] == "mCRC-BRAF-V600E"

    @patch("fetch_pubmed.esearch", return_value=["12345678"])
    @patch("fetch_pubmed.efetch")
    @patch("fetch_pubmed.load_tracked_dois")
    @patch("fetch_pubmed.load_queries")
    def test_deduplicates_tracked_dois(self, mock_queries, mock_tracked, mock_efetch, mock_esearch):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {"pubmed_query": "test"},
        }
        mock_tracked.return_value = {"10.1056/NEJMoa9999999": {"topic": "mCRC-BRAF-V600E"}}
        mock_efetch.return_value = [{
            "pmid": "12345678",
            "doi": "10.1056/NEJMoa9999999",
            "title": "Already tracked",
            "authors": "",
            "journal": "",
            "year": "",
            "abstract": "",
        }]

        results = fetch_pubmed(topic="mCRC-BRAF-V600E")
        assert len(results) == 0

    @patch("fetch_pubmed.esearch", return_value=[])
    @patch("fetch_pubmed.load_tracked_dois", return_value={})
    @patch("fetch_pubmed.load_queries")
    def test_handles_no_results(self, mock_queries, mock_tracked, mock_esearch):
        mock_queries.return_value = {
            "mCRC-BRAF-V600E": {"pubmed_query": "test"},
        }
        results = fetch_pubmed(topic="mCRC-BRAF-V600E")
        assert results == []
