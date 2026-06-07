"""Main entry point: orchestrate Layer 1 → 2 → 3 pipeline."""

import argparse
from datetime import date, datetime

from classify import classify_all
from config import (
    is_conference_season,
    load_tracked_abstracts,
    load_tracked_dois,
    save_tracked_abstracts,
    save_tracked_dois,
)
from create_issues import create_issues
from fetch_pubmed import fetch_pubmed
from fetch_rss import fetch_rss
from notify_line import notify_papers


def deduplicate_candidates(candidates):
    """Remove duplicates across sources (prefer PubMed > RSS)."""
    seen = {}
    source_priority = {"pubmed": 0, "pubmed_supplement": 0, "rss": 1}

    for c in candidates:
        key = c.get("doi") or c.get("pmid") or c.get("title", "")
        if not key:
            continue
        priority = source_priority.get(c.get("source", ""), 2)
        if key not in seen or priority < source_priority.get(seen[key].get("source", ""), 2):
            seen[key] = c

    return list(seen.values())


def run_pipeline(topic=None, dry_run=False, daily_mode=False, bootstrap=False):
    """Run the full paper-watch pipeline.

    Sources: PubMed (primary) + RSS feeds (supplementary).
    During conference season: also searches JCO/AnnOncol/DCR meeting abstract supplements.

    bootstrap: if True, use a 730-day PubMed window to seed a new topic.
    """
    # In daily mode (conference cron), check if we're in conference season
    if daily_mode:
        in_season, conf_name = is_conference_season()
        if not in_season:
            print("[Pipeline] Not in conference season. Skipping daily scan.")
            return
        print(f"[Pipeline] Conference season active: {conf_name}")

    reldate = 730 if bootstrap else None

    print(f"[Pipeline] Starting paper-watch — {datetime.now().isoformat()}")
    print(f"  Topic filter: {topic or 'all'}")
    print(f"  Dry run: {dry_run}")
    if bootstrap:
        print("  Bootstrap mode: 730-day PubMed window")
    print()

    # Layer 1: Fetch from PubMed + RSS
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

    # Deduplicate
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
  python main.py --dry-run                            # Full pipeline, print only
  python main.py --topic mCRC-BRAF-V600E              # Single topic
  python main.py --daily                              # Conference-season aware daily scan
  python main.py --bootstrap --topic generic-CRS      # Seed new topic with 2-year history
        """,
    )
    parser.add_argument("--topic", help="Single topic to process (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't create issues or update tracking")
    parser.add_argument("--daily", action="store_true", help="Daily mode: only run during conference season")
    parser.add_argument("--bootstrap", action="store_true", help="Seed a new topic with 2-year PubMed history")
    args = parser.parse_args()

    run_pipeline(
        topic=args.topic,
        dry_run=args.dry_run,
        daily_mode=args.daily,
        bootstrap=args.bootstrap,
    )


if __name__ == "__main__":
    main()
