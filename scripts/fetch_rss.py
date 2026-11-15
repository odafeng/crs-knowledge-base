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

from config import PUBMED_RELDATE, is_tracked, load_queries, load_tracked_dois, tracked_ids
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


# Words nearly every colorectal paper contains. They cannot tell topics apart: while they
# counted, any paper mentioning "colorectal" went to whichever topic was listed first
# (BRAF), whose agent then scored it as off-topic.
GENERIC_TERMS = frozenset({"colorectal", "colon", "rectal"})
# The designed catch-all for CRC papers that fit no specific topic (see its agent context).
FALLBACK_TOPIC = "generic-CRS"


def _term_hits(entry, terms) -> int:
    """How many terms appear as whole words in the title or abstract.

    Whole words, because substring matching found "TME" inside "treatment".
    """
    text = " ".join(entry.get(k, "") or "" for k in ("title", "abstract", "description"))
    return sum(
        1 for term in terms if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.IGNORECASE)
    )


def _matches_topic(entry, filter_terms):
    """Check if an entry matches any of the filter terms (title + abstract)."""
    return _term_hits(entry, filter_terms) > 0


def _specific_terms(cfg) -> list[str]:
    terms = cfg.get("rss_filter_terms", []) or cfg.get("keywords", [])
    return [t for t in terms if t.lower() not in GENERIC_TERMS]


def _assign_topic(article, topics_config):
    """Topic whose specific terms match best (first listed wins a tie).

    A paper matching no topic's specific terms goes to the catch-all topic when it is
    configured, else ''.
    """
    best, best_hits = "", 0
    for t, cfg in topics_config.items():
        hits = _term_hits(article, _specific_terms(cfg))
        if hits > best_hits:
            best, best_hits = t, hits
    if best:
        return best
    return FALLBACK_TOPIC if FALLBACK_TOPIC in topics_config else ""


def fetch_rss(topic=None, dry_run=False, reldate=PUBMED_RELDATE):
    """Fetch new colorectal papers from high-impact journals via PubMed.

    Returns list of candidate dicts. Raises AllFeedsFailedError if every
    journal query errors (so the workflow turns red instead of silently
    succeeding). A journal that simply has no new papers is NOT a failure.
    """
    queries = load_queries()
    tracked_dois, tracked_pmids = tracked_ids(load_tracked_dois())
    feeds = queries.get("rss_feeds", [])
    topics_config = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}

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
            if is_tracked(art, tracked_dois, tracked_pmids) or (uid and uid in seen_ids):
                continue

            # With a topic filter, keep only papers that belong to that topic; assigning
            # the requested topic to every colorectal paper sent them to the wrong agent.
            t = _assign_topic(art, topics_config)
            if not t or (topic and t != topic):
                continue

            candidate = {
                "pmid": art.get("pmid", ""),
                "doi": doi,
                "title": art.get("title", ""),
                "authors": art.get("authors", ""),
                "journal": name,
                "year": art.get("year", "") or str(datetime.now().year),
                "abstract": art.get("abstract", "") or "",
                "publication_types": art.get("publication_types", []),
                "comment_on_pmids": art.get("comment_on_pmids", []),
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
