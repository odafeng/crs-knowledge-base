"""Tests for how processed papers are recorded and recognised on later runs."""

from unittest.mock import patch

from config import is_tracked, tracked_ids, tracking_key
from fetch_pubmed import fetch_pubmed
from fetch_rss import fetch_rss
from main import update_tracking

NO_DOI = {"pmid": "42000001", "doi": "", "title": "[Japanese-language review]", "abstract": "", "topic": "mCRC-HER2"}


def test_tracking_key_prefers_doi_then_pmid():
    assert tracking_key({"doi": "10.1/x", "pmid": "1"}) == "10.1/x"
    assert tracking_key({"doi": "", "pmid": "42000001"}) == "pmid:42000001"
    assert tracking_key({"doi": "", "pmid": ""}) is None


def test_tracked_ids_reads_keys_and_entry_pmids():
    tracked = {
        "10.1/a": {"topic": "t", "pmid": "111"},
        "10.1/legacy": {"topic": "t"},  # recorded before PMIDs were stored
        "pmid:222": {"topic": "t", "pmid": "222"},
    }
    dois, pmids = tracked_ids(tracked)
    assert dois == {"10.1/a", "10.1/legacy"}
    assert pmids == {"111", "222"}
    # Recognised by PMID even if PubMed has since added a DOI to the record.
    assert is_tracked({"doi": "10.1/new", "pmid": "222"}, dois, pmids)
    assert not is_tracked({"doi": "10.1/new", "pmid": "333"}, dois, pmids)


def test_paper_without_doi_is_recorded_by_pmid():
    """First live run: 5 papers without a DOI were classified and never recorded."""
    paper = {**NO_DOI, "ai_score": 2, "ai_parse_failed": False}
    with (
        patch("main.load_tracked_dois", return_value={}),
        patch("main.load_tracked_abstracts", return_value={}),
        patch("main.save_tracked_dois") as save,
        patch("main.save_tracked_abstracts"),
    ):
        update_tracking([paper], [], "2026-11-15")
    tracked = save.call_args.args[0]
    assert tracked["pmid:42000001"] == {"topic": "mCRC-HER2", "added": "2026-11-15", "score": 2, "pmid": "42000001"}


@patch("fetch_pubmed.esearch", return_value=["42000001"])
@patch("fetch_pubmed.efetch", return_value=[dict(NO_DOI)])
@patch("fetch_pubmed.load_tracked_dois", return_value={"pmid:42000001": {"topic": "mCRC-HER2", "pmid": "42000001"}})
@patch("fetch_pubmed.load_queries", return_value={"mCRC-HER2": {"pubmed_query": "q"}})
def test_pubmed_skips_paper_tracked_by_pmid(_queries, _tracked, _efetch, _esearch):
    assert fetch_pubmed(topic="mCRC-HER2") == []


@patch("fetch_rss.esearch", return_value=["42000001"])
@patch("fetch_rss.efetch", return_value=[{**NO_DOI, "title": "HER2 colorectal review"}])
@patch("fetch_rss.load_tracked_dois", return_value={"pmid:42000001": {"topic": "mCRC-HER2", "pmid": "42000001"}})
@patch("fetch_rss.load_queries")
def test_journal_feed_skips_paper_tracked_by_pmid(mock_queries, _tracked, _efetch, _esearch):
    mock_queries.return_value = {
        "mCRC-HER2": {"rss_filter_terms": ["HER2"]},
        "rss_feeds": [{"name": "JCO", "pubmed_journal": "J Clin Oncol"}],
    }
    assert fetch_rss() == []
