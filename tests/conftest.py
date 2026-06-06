"""Shared fixtures for paper-watch tests."""

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import modules
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def sample_pubmed_xml():
    """Minimal PubMed efetch XML for one article."""
    return b"""<?xml version="1.0" ?>
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345678</PMID>
          <Article>
            <ArticleTitle>Test Article About BRAF V600E in Colorectal Cancer</ArticleTitle>
            <Journal>
              <ISOAbbreviation>N Engl J Med</ISOAbbreviation>
              <JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue>
            </Journal>
            <Abstract>
              <AbstractText>This phase 3 trial evaluated encorafenib plus cetuximab in mCRC.</AbstractText>
            </Abstract>
            <AuthorList>
              <Author><LastName>Smith</LastName><Initials>J</Initials></Author>
              <Author><LastName>Doe</LastName><Initials>A</Initials></Author>
            </AuthorList>
          </Article>
        </MedlineCitation>
        <PubmedData>
          <ArticleIdList>
            <ArticleId IdType="doi">10.1056/NEJMoa9999999</ArticleId>
          </ArticleIdList>
        </PubmedData>
      </PubmedArticle>
    </PubmedArticleSet>"""


@pytest.fixture
def sample_candidate():
    """A single candidate paper dict."""
    return {
        "pmid": "12345678",
        "doi": "10.1056/NEJMoa9999999",
        "title": "Test Article About BRAF V600E in Colorectal Cancer",
        "authors": "Smith J, Doe A",
        "journal": "N Engl J Med",
        "year": "2026",
        "abstract": "This phase 3 trial evaluated encorafenib plus cetuximab in mCRC.",
        "topic": "mCRC-BRAF-V600E",
        "source": "pubmed",
    }


@pytest.fixture
def sample_classified_paper(sample_candidate):
    """A candidate that has been through AI classification."""
    paper = sample_candidate.copy()
    paper.update({
        "ai_score": 5,
        "ai_analysis": "這是一篇重要的 Phase 3 RCT 更新",
        "ai_bottom_line": "EC+化療一線治療確認 OS 獲益",
        "ai_suggested_js": {
            "id": "test-2026",
            "year": 2026,
            "journal": "NEJM",
            "studyType": "Phase 3 RCT",
        },
        "ai_suggested_filename": "Smith_NEJM_2026_TestTrial.html",
        "ai_relations": [{"targetId": "beacon-2019", "type": "builds_on"}],
    })
    return paper


@pytest.fixture
def tracked_dois_data():
    """Minimal tracked DOIs for testing dedup."""
    return {
        "10.1056/NEJMoa1908075": {"topic": "mCRC-BRAF-V600E", "added": "2026-06-06"},
        "10.1200/JCO.20.02088": {"topic": "mCRC-BRAF-V600E", "added": "2026-06-06"},
    }
