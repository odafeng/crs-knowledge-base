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


# Tracking state lives in data/*.json until cutover; with GUTHUB_CONTENT_DATABASE_URL set (a Cloud Run job, which has
# no persistent disk) it lives in app.paper_watch_state, moved there by content_writer.py cutover (E3 #76, ADR-0021).
CONTENT_DATABASE_ENV = "GUTHUB_CONTENT_DATABASE_URL"


def _load_state(name: str, path: Path) -> dict:
    url = os.environ.get(CONTENT_DATABASE_ENV)
    if url:
        import psycopg

        with psycopg.connect(url) as conn:
            row = conn.execute("select data from app.paper_watch_state where name = %s", (name,)).fetchone()
        return row[0] if row else {}
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _save_state(name: str, path: Path, data: dict) -> None:
    url = os.environ.get(CONTENT_DATABASE_ENV)
    if url:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(url) as conn:
            conn.execute(
                "insert into app.paper_watch_state (name, data) values (%s, %s)"
                " on conflict (name) do update set data = excluded.data, updated_at = now()",
                (name, Jsonb(data)),
            )
        return
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_tracked_dois():
    return _load_state("tracked-dois", TRACKED_DOIS_FILE)


def save_tracked_dois(data):
    _save_state("tracked-dois", TRACKED_DOIS_FILE, data)


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
    return _load_state("tracked-abstracts", TRACKED_ABSTRACTS_FILE)


def save_tracked_abstracts(data):
    _save_state("tracked-abstracts", TRACKED_ABSTRACTS_FILE, data)


def load_kb_data_from_conn(conn) -> dict:
    """Read active topics, papers, relations, and commentary directly from PostgreSQL (K9 #259, ADR-0027)."""
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        topic_rows = cur.execute("select key, standard_of_care, soc_title, metrics from app.topics").fetchall()
        paper_rows = cur.execute(
            "select id, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line,"
            " doi, source, reviewed_at, added_at, source_file, review_status, review_published_at, summary"
            " from app.papers where withdrawn_at is null order by year desc, id"
        ).fetchall()
        rel_rows = cur.execute(
            "select paper_id, target_id, type from app.paper_relations order by paper_id, target_id, type"
        ).fetchall()
        comm_rows = cur.execute(
            "select paper_id, doi, pmid, title, journal, year, type, summary, critique, new_data,"
            " added_at, review_status, review_published_at"
            " from app.research_commentary order by paper_id, added_at, coalesce(doi, pmid, title)"
        ).fetchall()

    relations: dict[str, list[dict]] = {}
    for r in rel_rows:
        relations.setdefault(r["paper_id"], []).append({"targetId": r["target_id"], "type": r["type"]})

    commentary: dict[str, list[dict]] = {}
    for c in comm_rows:
        item = {k: v for k, v in (("doi", c["doi"]), ("pmid", c["pmid"])) if v}
        item |= {
            "title": c["title"],
            "journal": c["journal"],
            "type": c["type"],
            "summary": c["summary"],
            "critique": c["critique"],
            "newData": c["new_data"],
            "addedAt": c["added_at"].isoformat(),
        }
        if c["year"] is not None:
            item["year"] = c["year"]
        if c["review_status"]:
            review = {"status": c["review_status"]}
            if c["review_published_at"]:
                review["publishedAt"] = c["review_published_at"].isoformat()
            item["review"] = review
        commentary.setdefault(c["paper_id"], []).append(item)

    data: dict[str, dict] = {}
    for t in topic_rows:
        block: dict = {"papers": [], "metrics": t["metrics"] or {}}
        if t["soc_title"] is not None or t["standard_of_care"]:
            soc: dict = {"cards": t["standard_of_care"] or []}
            if t["soc_title"] is not None:
                soc["title"] = t["soc_title"]
            block["standard_of_care"] = soc
        data[t["key"]] = block

    for p in paper_rows:
        entry: dict = {
            "id": p["id"],
            "year": p["year"],
            "journal": p["journal"],
            "studyType": p["study_type"],
            "n": p["n"],
            "regimen": p["regimen"],
            "endpoint": p["endpoint"],
            "result": p["result"],
            "bottomLine": p["bottom_line"],
            "doi": p["doi"] or "",
            "relations": relations.get(p["id"], []),
            "source": p["source"],
            "reviewedAt": p["reviewed_at"].isoformat(),
        }
        if p["added_at"]:
            entry["addedAt"] = p["added_at"].isoformat()
        if p["source_file"]:
            entry["file"] = p["source_file"]
        if p["id"] in commentary:
            entry["commentary"] = commentary[p["id"]]
        if p["summary"]:
            entry["summary"] = p["summary"]
        if p["review_status"]:
            review = {"status": p["review_status"]}
            if p["review_published_at"]:
                review["publishedAt"] = p["review_published_at"].isoformat()
            entry["review"] = review
        data.setdefault(p["topic_key"], {"papers": [], "metrics": {}})["papers"].append(entry)

    return data


def load_kb_data() -> dict:
    """Load KB data from PostgreSQL when GUTHUB_CONTENT_DATABASE_URL is set, else local data/papers.json."""
    url = os.environ.get(CONTENT_DATABASE_ENV)
    if url:
        import psycopg

        with psycopg.connect(url) as conn:
            return load_kb_data_from_conn(conn)
    if PAPERS_JSON.exists():
        return json.loads(PAPERS_JSON.read_text(encoding="utf-8"))
    return {}
