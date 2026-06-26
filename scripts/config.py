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
CLASSIFY_MODEL = "claude-sonnet-4-6"

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


def load_tracked_abstracts():
    if TRACKED_ABSTRACTS_FILE.exists():
        with open(TRACKED_ABSTRACTS_FILE) as f:
            return json.load(f)
    return {}


def save_tracked_abstracts(data):
    with open(TRACKED_ABSTRACTS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
