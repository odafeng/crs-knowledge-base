"""Main entry point: orchestrate Layer 1 → 2 → 3 pipeline."""

import argparse
import json
import sys
from datetime import date, datetime

from config import (
    DATA_DIR,
    load_queries,
    load_tracked_abstracts,
    load_tracked_dois,
    save_tracked_abstracts,
    save_tracked_dois,
)
from fetch_pubmed import fetch_pubmed
from fetch_rss import fetch_rss
from fetch_conferences import fetch_conferences
from fetch_news import fetch_news
from classify import classify_all
from create_issues import create_issues
from create_pr import create_prs
from notify_line import notify_papers


def is_conference_season():
    """Check if today falls within a major conference window."""
    queries = load_queries()
    seasons = queries.get("conference_seasons", {})
    today = date.today()
    today_md = today.strftime("%m-%d")

    for key, season in seasons.items():
        if season["start"] <= today_md <= season["end"]:
            return True, season["name"]
    return False, None


def deduplicate_candidates(candidates):
    """Remove duplicates across sources (prefer PubMed > RSS > conference)."""
    seen = {}
    source_priority = {"pubmed": 0, "rss": 1, "asco": 2, "esmo": 2}

    for c in candidates:
        key = c.get("doi") or c.get("pmid") or c.get("abstract_id") or c.get("title", "")
        if not key:
            continue
        priority = source_priority.get(c.get("source", ""), 3)
        if key not in seen or priority < source_priority.get(seen[key].get("source", ""), 3):
            seen[key] = c

    return list(seen.values())


def run_pipeline(topic=None, skip_conferences=False, dry_run=False, daily_mode=False, bootstrap=False):
    """Run the full paper-watch pipeline.

    bootstrap: if True, use a 730-day PubMed window to seed a new topic
               with its foundational literature.
    """
    # In daily mode (conference cron), check if we're in conference season
    if daily_mode:
        in_season, conf_name = is_conference_season()
        if not in_season:
            print("[Pipeline] Not in conference season. Skipping daily scan.")
            return
        print(f"[Pipeline] Conference season active: {conf_name}")

    reldate = 730 if bootstrap else None  # None = use default (14 days)

    print(f"[Pipeline] Starting paper-watch — {datetime.now().isoformat()}")
    print(f"  Topic filter: {topic or 'all'}")
    print(f"  Dry run: {dry_run}")
    if bootstrap:
        print(f"  Bootstrap mode: 730-day PubMed window")
    print()

    # Layer 1: Fetch from all sources
    candidates = []

    pubmed_kwargs = {"topic": topic, "dry_run": False}
    if reldate:
        pubmed_kwargs["reldate"] = reldate
    pubmed_results = fetch_pubmed(**pubmed_kwargs)
    candidates.extend(pubmed_results)
    print()

    rss_results = fetch_rss(topic=topic, dry_run=False)
    candidates.extend(rss_results)
    print()

    if not skip_conferences:
        conf_results = fetch_conferences(topic=topic, dry_run=False)
        candidates.extend(conf_results)
        print()

    # During conference season: also search medical news sites
    in_season, _ = is_conference_season()
    if in_season and not skip_conferences:
        print("[Pipeline] Conference season — searching news sites...")
        news_results = fetch_news(topic=topic, dry_run=False)
        candidates.extend(news_results)
        print()

    # Deduplicate across sources
    candidates = deduplicate_candidates(candidates)
    print(f"[Pipeline] Total unique candidates: {len(candidates)}")

    if not candidates:
        print("[Pipeline] No new papers found. Done.")
        return

    # Layer 2: AI classification with topic-specific sub-agents
    print()
    classified = classify_all(candidates, dry_run=dry_run)
    print(f"[Pipeline] Papers passing relevance threshold: {len(classified)}")

    if not classified:
        print("[Pipeline] No high-relevance papers. Done.")
        return

    # Layer 3: All ≥4 papers get GitHub Issues for human review
    print(f"\n[Pipeline] {len(classified)} papers → GitHub Issues")
    create_issues(classified, dry_run=dry_run)

    # LINE notification for all high-relevance papers
    print()
    notify_papers(classified, dry_run=dry_run)

    # Update tracking files (unless dry run)
    if not dry_run:
        tracked_dois = load_tracked_dois()
        tracked_abstracts = load_tracked_abstracts()
        today_str = date.today().isoformat()

        for c in classified:
            if c.get("doi"):
                tracked_dois[c["doi"]] = {"topic": c.get("topic", ""), "added": today_str}
            if c.get("abstract_id"):
                tracked_abstracts[c["abstract_id"]] = {"topic": c.get("topic", ""), "added": today_str}

        save_tracked_dois(tracked_dois)
        save_tracked_abstracts(tracked_abstracts)
        print("\n[Pipeline] Updated tracking files.")

    print(f"\n[Pipeline] Done — {datetime.now().isoformat()}")


def main():
    parser = argparse.ArgumentParser(
        description="CRS Knowledge Base Paper Watch Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --dry-run                              # Full pipeline, print only
  python main.py --topic mCRC-BRAF-V600E                # Single topic
  python main.py --daily                                # Conference-season aware daily scan
  python main.py --skip-conferences                     # PubMed + RSS only
  python main.py --bootstrap --topic generic-CRS      # Seed new topic with 2-year history
        """,
    )
    parser.add_argument("--topic", help="Single topic to process (default: all)")
    parser.add_argument("--skip-conferences", action="store_true", help="Skip conference abstract scraping")
    parser.add_argument("--dry-run", action="store_true", help="Don't create issues or update tracking")
    parser.add_argument("--daily", action="store_true", help="Daily mode: only run during conference season")
    parser.add_argument("--bootstrap", action="store_true", help="Seed a new topic with 2-year PubMed history")
    args = parser.parse_args()

    run_pipeline(
        topic=args.topic,
        skip_conferences=args.skip_conferences,
        dry_run=args.dry_run,
        daily_mode=args.daily,
        bootstrap=args.bootstrap,
    )


if __name__ == "__main__":
    main()
