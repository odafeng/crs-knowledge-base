"""Layer 1b: Fetch new papers from high-impact journals.

Historically this scraped publisher RSS feeds directly, but publishers
aggressively block automated clients (HTTP 403), move feed URLs (404), or
discontinue feeds entirely (410 Gone). That made the whole RSS layer silently
dead while the workflow still reported success.

Instead we now query each journal through NCBI E-utilities (PubMed) — the same
endpoint the PubMed layer already uses successfully. PubMed indexes every one
of these journals, is not bot-blocked, and lets us scope to colorectal papers.
The public function name `fetch_rss` is kept for backward compatibility with
the pipeline and CLI.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime

from config import PUBMED_RELDATE, load_queries, load_tracked_dois
from fetch_pubmed import efetch, esearch

# Colorectal scope applied to every journal query so we only pull relevant papers.
CRC_FILTER = (
    "(colorectal[tiab] OR colon[tiab] OR rectal[tiab] OR colorectal neoplasms[MeSH] "
    "OR rectal neoplasms[MeSH] OR colonic neoplasms[MeSH])"
)


class AllFeedsFailedError(RuntimeError):
    """Raised when every journal feed query errors out (likely an outage).

    Lets the pipeline fail loudly instead of silently reporting success with
    zero results — the failure mode that previously hid 8 dead feeds.
    """


def _journal_query(journal: str) -> str:
    """Build a PubMed query for recent colorectal papers in one journal."""
    return f'("{journal}"[Journal]) AND {CRC_FILTER}'


def _extract_doi(text):
    """Extract DOI from text or URL."""
    if not text:
        return ""
    m = re.search(r"(10\.\d{4,}/[^\s<>\"]+)", text)
    return m.group(1).rstrip(".,;") if m else ""


def _matches_topic(entry, filter_terms):
    """Check if an entry matches any of the filter terms (title + abstract)."""
    text = (entry.get("title", "") + " " + entry.get("abstract", "") + " " + entry.get("description", "")).lower()
    return any(term.lower() in text for term in filter_terms)


def _assign_topic(article, topics_config):
    """Return the first topic whose filter terms / keywords match, else ''."""
    for t, cfg in topics_config.items():
        terms = cfg.get("rss_filter_terms", []) or cfg.get("keywords", [])
        if _matches_topic(article, terms):
            return t
    return ""


def fetch_rss(topic=None, dry_run=False, reldate=PUBMED_RELDATE):
    """Fetch new colorectal papers from high-impact journals via PubMed.

    Returns list of candidate dicts. Raises AllFeedsFailedError if every
    journal query errors (so the workflow turns red instead of silently
    succeeding). A journal that simply has no new papers is NOT a failure.
    """
    queries = load_queries()
    tracked = load_tracked_dois()
    tracked_doi_set = set(tracked.keys())
    feeds = queries.get("rss_feeds", [])
    topics_config = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}

    if topic:
        topics_config = {k: v for k, v in topics_config.items() if k == topic}

    candidates = []
    seen_ids = set()
    attempted = 0
    errored = 0

    for feed in feeds:
        name = feed["name"]
        journal = feed.get("pubmed_journal", name)
        print(f"[Journal] Fetching {name} ({journal}) ...")
        attempted += 1

        try:
            pmids = esearch(_journal_query(journal), reldate=reldate)
            time.sleep(0.34)  # NCBI rate limit
            articles = efetch(pmids) if pmids else []
            time.sleep(0.34)
        except Exception as e:  # degrade per-feed; fail loud only if all fail
            print(f"  [WARN] Failed to query {name}: {e}", file=sys.stderr)
            errored += 1
            continue

        print(f"  Got {len(articles)} colorectal article(s)")

        for art in articles:
            doi = art.get("doi", "")
            uid = doi or art.get("pmid", "")
            if uid and (uid in seen_ids or doi in tracked_doi_set):
                continue

            t = topic if topic else _assign_topic(art, topics_config)
            if not t:
                continue  # no matching topic — skip, same as the old RSS behavior

            candidate = {
                "pmid": art.get("pmid", ""),
                "doi": doi,
                "title": art.get("title", ""),
                "authors": art.get("authors", ""),
                "journal": name,
                "year": art.get("year", "") or str(datetime.now().year),
                "abstract": (art.get("abstract", "") or "")[:500],
                "topic": t,
                "source": "journal",
                "link": f"https://doi.org/{doi}" if doi else "",
            }
            candidates.append(candidate)
            if uid:
                seen_ids.add(uid)

    # Health check: if we tried feeds and every single one errored, that's an
    # outage (e.g. NCBI down). Fail loudly rather than pretend everything's fine.
    if attempted and errored == attempted:
        raise AllFeedsFailedError(f"All {attempted} journal feeds failed to fetch — likely an outage.")

    if errored:
        print(f"  [Journal] {errored}/{attempted} feeds errored (continuing with the rest).", file=sys.stderr)

    if dry_run:
        print(f"\n[DRY RUN] Journal candidates: {len(candidates)}")
        for c in candidates:
            print(f"  [{c['topic']}] {c['journal']}: {c['title'][:80]}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch new papers from high-impact journals via PubMed")
    parser.add_argument("--topic", help="Single topic to filter (default: all)")
    parser.add_argument("--reldate", type=int, default=PUBMED_RELDATE, help="Search window in days")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = fetch_rss(topic=args.topic, dry_run=args.dry_run, reldate=args.reldate)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
