"""Main entry point: orchestrate Layer 1 → 2 → 3 pipeline."""

import argparse
import json
import sys
from datetime import date, datetime

from anthropic import Anthropic

from classify import classify_all
from commentary import CommentaryProposal, kb_papers, split_commentary, triage_commentary
from config import (
    ANTHROPIC_API_KEY,
    PAPERS_JSON,
    is_conference_season,
    load_tracked_abstracts,
    load_tracked_dois,
    save_tracked_abstracts,
    save_tracked_dois,
    tracking_key,
)
from content_store import content_session
from create_issues import create_commentary_review_issue, create_issues
from fetch_pubmed import fetch_pubmed, resolve_dois
from fetch_rss import AllFeedsFailedError, fetch_rss
from notify_line import notify_papers
from paper_summary import summarize_new
from provenance import abstract_status, evaluate_commentary_gate, evaluate_paper_gate
from publish import AUTO_PUBLISH_TOPICS, PublishError, publish_commentary, publish_paper
from usage import USAGE


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


def triage_all_commentary(commentary: list[dict], dry_run: bool) -> list[tuple[dict, CommentaryProposal | None]]:
    """Lightweight triage for editorials/letters/comments/news (no full agent)."""
    if not commentary:
        return []
    if dry_run or not ANTHROPIC_API_KEY:
        print(f"[Commentary] Skipping triage of {len(commentary)} commentary item(s) (dry run or no API key)")
        return []
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    kb = kb_papers(json.loads(PAPERS_JSON.read_text()))
    results = []
    for c in commentary:
        print(f"[Commentary] {c.get('title', '')[:70]}")
        proposal = triage_commentary(client, c, kb, resolve_dois)
        target = proposal.target_id if proposal else None
        print(f"  → {target or 'no KB trial (tracked only)'}")
        results.append((c, proposal))
    return results


def publish_or_hold(classified: list[dict], today: str, dry_run: bool) -> tuple[list[dict], list[dict]]:
    """Publish papers that pass the provenance gate; hold the rest for review (ADR-0013)."""
    published, held = [], []
    for paper in classified:
        reasons = evaluate_paper_gate(paper, AUTO_PUBLISH_TOPICS).reasons
        if not reasons and not dry_run:
            try:
                target = paper.get("doi") or f"pmid:{paper.get('pmid')}"
                with content_session("publish_paper", target) as session:
                    if session.done is None:
                        entry = publish_paper(paper, "auto", today, **session.kb_args)
                        session.record(f"publish {entry['id']} ({entry['file']})")
                        paper["kb_id"] = entry["id"]
                print(f"  [Publish] {session.done or session.summary}")
            except PublishError as e:
                reasons = e.reasons
        if reasons:
            paper["gate_reasons"] = reasons
            paper["publish_status"] = "held"
            held.append(paper)
        else:
            paper["publish_status"] = "auto"
            published.append(paper)
    return published, held


def publish_or_hold_commentary(
    triaged: list[tuple[dict, CommentaryProposal | None]], today: str, dry_run: bool
) -> list[CommentaryProposal]:
    """Publish commentary PubMed itself links to a KB trial; return the rest for review."""
    auto, held = [], []
    for paper, proposal in triaged:
        if not proposal or not proposal.target_id:
            continue
        gate = evaluate_commentary_gate(proposal, paper.get("abstract", ""))
        (auto if gate.passed else held).append(proposal)
    if auto and not dry_run:
        try:
            items = [(p.target_id, p.to_entry(today)) for p in auto]
            with content_session("publish_commentary", ",".join(sorted({t for t, _ in items}))) as session:
                if session.done is None:
                    changed = publish_commentary(items, "auto", today, **session.kb_args)
                    session.record(f"commentary on {', '.join(changed) or 'nothing new'}")
            print(f"  [Publish] {session.done or session.summary}")
        except PublishError as e:
            print(f"  [WARN] Commentary publish failed, sending to review: {e}", file=sys.stderr)
            held += auto
    return held


def update_tracking(research: list[dict], triaged: list[tuple[dict, CommentaryProposal | None]], today: str) -> None:
    """Record every processed candidate so it is not fetched and classified again.

    Low-score papers are recorded too (with their score); previously only score ≥4
    and parse failures were, so the rest were re-classified on every run in the
    search window. Unclassified papers (no API key) are not recorded.
    """
    tracked_dois = load_tracked_dois()
    tracked_abstracts = load_tracked_abstracts()

    def record(c: dict, extra: dict) -> None:
        entry = {"topic": c.get("topic", ""), "added": today, **extra}
        if c.get("pmid"):
            entry["pmid"] = c["pmid"]
        # Keyed by DOI, or by PMID for the papers PubMed lists without one; those were
        # never recorded before and were re-classified on every run.
        key = tracking_key(c)
        if key:
            tracked_dois[key] = entry
        if c.get("abstract_id"):
            tracked_abstracts[c["abstract_id"]] = entry

    for c in research:
        if c.get("ai_score") is not None or c.get("ai_parse_failed"):
            record(c, {"score": c.get("ai_score")})
    for c, proposal in triaged:
        if proposal is None:
            # The model declined; leave it untracked so the next run retries it.
            print(f"  [Commentary] Not tracked (declined, will retry): {c.get('title', '')[:60]}")
            continue
        record(c, {"kind": "commentary", "target": proposal.target_id})

    save_tracked_dois(tracked_dois)
    save_tracked_abstracts(tracked_abstracts)
    print("\n[Pipeline] Updated tracking files.")


def run_pipeline(topic=None, dry_run=False, daily_mode=False, bootstrap=False, reldate=None):
    """Run the full paper-watch pipeline.

    Sources: PubMed (primary) + RSS feeds (supplementary).
    During conference season: also searches JCO/AnnOncol/DCR meeting abstract supplements.

    bootstrap: if True, use a 730-day PubMed window to seed a new topic.
    reldate: a one-off wider PubMed window in days, to catch papers an earlier query missed.
    """
    # In daily mode (conference cron), check if we're in conference season
    if daily_mode:
        in_season, conf_name = is_conference_season()
        if not in_season:
            print("[Pipeline] Not in conference season. Skipping daily scan.")
            return False
        print(f"[Pipeline] Conference season active: {conf_name}")

    reldate = reldate or (730 if bootstrap else None)

    print(f"[Pipeline] Starting paper-watch — {datetime.now().isoformat()}")
    print(f"  Topic filter: {topic or 'all'}")
    print(f"  Dry run: {dry_run}")
    if reldate:
        print(f"  PubMed window: {reldate} days")
    print()

    # Layer 1: Fetch from PubMed + RSS
    candidates = []

    pubmed_kwargs = {"topic": topic, "dry_run": False}
    if reldate:
        pubmed_kwargs["reldate"] = reldate
    pubmed_results = fetch_pubmed(**pubmed_kwargs)
    candidates.extend(pubmed_results)
    print()

    # Journal feeds (via PubMed). A total outage is reported at the end so the
    # workflow turns red, but we still process the PubMed papers we already have.
    journal_outage = False
    try:
        rss_results = fetch_rss(topic=topic, dry_run=False)
        candidates.extend(rss_results)
    except AllFeedsFailedError as e:
        print(f"[Pipeline] ERROR: {e}", file=sys.stderr)
        journal_outage = True
    print()

    # Deduplicate
    candidates = deduplicate_candidates(candidates)
    print(f"[Pipeline] Total unique candidates: {len(candidates)}")

    if not candidates:
        print("[Pipeline] No new papers found. Done.")
        return journal_outage

    today_str = date.today().isoformat()
    for c in candidates:
        c["abstract_status"] = abstract_status(c.get("abstract", ""))
    research, commentary = split_commentary(candidates)
    print(f"[Pipeline] {len(research)} research, {len(commentary)} commentary")

    # Commentary: lightweight triage. Never a new-paper issue. Items PubMed links to
    # a KB trial are published; other mapped items go to one review issue; unmapped
    # ones are only tracked.
    triaged = triage_all_commentary(commentary, dry_run)
    held_commentary = publish_or_hold_commentary(triaged, today_str, dry_run)
    create_commentary_review_issue(held_commentary, today_str, dry_run=dry_run)

    # Layer 2: AI classification with topic-specific sub-agents
    print()
    classified = classify_all(research, dry_run=dry_run)
    print(f"[Pipeline] Papers passing relevance threshold: {len(classified)}")

    if classified:
        # Layer 3: papers passing the provenance gate are published; the rest get
        # a review issue with the reasons (ADR-0013)
        published, held = publish_or_hold(classified, today_str, dry_run)
        print(f"\n[Pipeline] {len(published)} published, {len(held)} held for review")
        create_issues(held, dry_run=dry_run)
        if not dry_run:  # the at-a-glance summary of each new paper (I2 #191)
            summarize_new([p["kb_id"] for p in published if p.get("kb_id")])

        # LINE notification for all high-relevance papers
        print()
        notify_papers(classified, dry_run=dry_run)
    else:
        print("[Pipeline] No high-relevance papers.")

    if not dry_run:
        update_tracking(research, triaged, today_str)

    USAGE.report()

    print(f"\n[Pipeline] Done — {datetime.now().isoformat()}")
    return journal_outage


def main():
    parser = argparse.ArgumentParser(
        description="Seminar Hegemon Paper Watch Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --dry-run                            # Full pipeline, print only
  python main.py --topic mCRC-BRAF-V600E              # Single topic
  python main.py --daily                              # Conference-season aware daily scan
  python main.py --bootstrap --topic generic-CRS      # Seed new topic with 2-year history
  python main.py --reldate 60 --topic generic-CRS     # One-off catch-up over the last 60 days
        """,
    )
    parser.add_argument("--topic", help="Single topic to process (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't create issues or update tracking")
    parser.add_argument("--daily", action="store_true", help="Daily mode: only run during conference season")
    parser.add_argument("--bootstrap", action="store_true", help="Seed a new topic with 2-year PubMed history")
    parser.add_argument("--reldate", type=int, help="PubMed window in days for a one-off catch-up scan")
    args = parser.parse_args()

    journal_outage = run_pipeline(
        topic=args.topic,
        dry_run=args.dry_run,
        daily_mode=args.daily,
        bootstrap=args.bootstrap,
        reldate=args.reldate,
    )

    # Fail loudly if every journal feed errored — never silently green again.
    if journal_outage:
        print("[Pipeline] Exiting non-zero: all journal feeds failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
