"""Shared constants for the paper-watch pipeline."""

import json
import os
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DATA_DIR = PROJECT_ROOT / "data"
QUERIES_FILE = SCRIPTS_DIR / "queries.json"
TRACKED_DOIS_FILE = DATA_DIR / "tracked-dois.json"
TRACKED_ABSTRACTS_FILE = DATA_DIR / "tracked-abstracts.json"
PAPERS_JSON = DATA_DIR / "papers.json"

# PubMed E-utilities
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUBMED_SEARCH_URL = f"{PUBMED_BASE}/esearch.fcgi"
PUBMED_FETCH_URL = f"{PUBMED_BASE}/efetch.fcgi"
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

# Claude API
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Most capable generally available model. Requires 30-day data retention on the
# organization (a ZDR org gets a 400 on every request).
CLASSIFY_MODEL = "claude-fable-5-2"
# Thinking depth for the classification agent. Set explicitly: gains above "high"
# are uneven on this model and turns get much slower.
CLASSIFY_EFFORT = "high"
# Commentary triage (editorials, letters) is a single short call: map to a KB trial,
# write one line, set two flags. Low effort is enough.
TRIAGE_EFFORT = "low"
# Server-side refusal fallback: if a safety classifier declines a request, the API
# re-runs it within the same call on a model chosen by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Stale-content review (check_stale.py): days since the last check before an item is listed.
STALE_PAPER_DAYS = 365
STALE_SOC_DAYS = 182  # 現行治療方案 is what clinicians read most; review it more often
STALE_REGULATORY_DAYS = 182

# GitHub
GITHUB_TOKEN = os.environ.get("GH_TOKEN", os.environ.get("GITHUB_TOKEN", ""))
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "")

# LINE push notification
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

# Search window
PUBMED_RELDATE = 14  # days

# AI classification threshold
# Score ≥4 → GitHub Issue for human review + LINE notification.
# No auto-PR or auto-merge. User decides whether to incorporate.
RELEVANCE_THRESHOLD = 4


def load_queries():
    with open(QUERIES_FILE) as f:
        return json.load(f)


def is_conference_season() -> tuple[bool, str | None]:
    """Check if today falls within a major conference window."""
    from datetime import date

    queries = load_queries()
    seasons = queries.get("conference_seasons", {})
    today_md = date.today().strftime("%m-%d")
    for season in seasons.values():
        start, end = season["start"], season["end"]
        if start <= end:
            in_season = start <= today_md <= end
        else:
            # Season wraps across year-end (e.g. "12-15" .. "01-10")
            in_season = today_md >= start or today_md <= end
        if in_season:
            return True, season["name"]
    return False, None


def load_tracked_dois():
    if TRACKED_DOIS_FILE.exists():
        with open(TRACKED_DOIS_FILE) as f:
            return json.load(f)
    return {}


def save_tracked_dois(data):
    with open(TRACKED_DOIS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# A processed paper is keyed by DOI; one PubMed lists without a DOI is keyed "pmid:<PMID>".
PMID_KEY_PREFIX = "pmid:"


def tracking_key(paper: dict) -> str | None:
    """Key under which a processed paper is recorded, or None if it has no identifier."""
    if paper.get("doi"):
        return paper["doi"]
    if paper.get("pmid"):
        return f"{PMID_KEY_PREFIX}{paper['pmid']}"
    return None


def tracked_ids(tracked: dict) -> tuple[set[str], set[str]]:
    """(DOIs, PMIDs) of every paper already processed.

    Entries carry the PMID when known, so a paper first seen without a DOI is still
    recognised after PubMed adds one.
    """
    dois = {k for k in tracked if not k.startswith(PMID_KEY_PREFIX)}
    pmids = {k[len(PMID_KEY_PREFIX) :] for k in tracked if k.startswith(PMID_KEY_PREFIX)}
    pmids |= {str(v["pmid"]) for v in tracked.values() if isinstance(v, dict) and v.get("pmid")}
    return dois, pmids


def is_tracked(paper: dict, dois: set[str], pmids: set[str]) -> bool:
    return bool((paper.get("doi") and paper["doi"] in dois) or (paper.get("pmid") and paper["pmid"] in pmids))


def load_tracked_abstracts():
    if TRACKED_ABSTRACTS_FILE.exists():
        with open(TRACKED_ABSTRACTS_FILE) as f:
            return json.load(f)
    return {}


def save_tracked_abstracts(data):
    with open(TRACKED_ABSTRACTS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
