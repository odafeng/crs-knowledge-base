"""Main entry point: orchestrate Layer 1 → 2 → 3 pipeline."""

import argparse
import sys
from datetime import date, datetime

from anthropic import Anthropic

from classify import MAX_REPAIR_ATTEMPTS, can_repair, classify_all, repair_paper
from commentary import CommentaryProposal, kb_papers, split_commentary, triage_commentary
from config import (
    ANTHROPIC_API_KEY,
    RELEVANCE_THRESHOLD,
    is_conference_season,
    load_kb_data,
    load_tracked_abstracts,
    load_tracked_dois,
    save_tracked_abstracts,
    save_tracked_dois,
    tracking_key,
)
from content_store import content_session
from create_issues import create_issues
from digest import accepted_digests, finish, picked
from fetch_pubmed import efetch, fetch_pubmed, resolve_dois
from fetch_rss import AllFeedsFailedError, fetch_rss
from news_writer import write_news_for_new
from notify_line import notify_papers
from paper_summary import summarize_new
from provenance import abstract_status, evaluate_commentary_gate, evaluate_paper_gate
from publish import AUTO_PUBLISH_TOPICS, PublishError, publish_commentary, publish_paper
from revalidate_site import revalidate_site
from usage import USAGE


def deduplicate_candidates(candidates):
    """Remove duplicates across sources (prefer PubMed > RSS) while unioning cross-specialty domains."""
    seen = {}
    source_priority = {"pubmed": 0, "pubmed_supplement": 0, "rss": 1, "journal": 1}

    def _collect_domains(item: dict) -> list[str]:
        found: list[str] = []
        if item.get("primary_domain"):
            found.append(item["primary_domain"])
        for sec in item.get("secondary_domains") or []:
            if sec and sec not in found:
                found.append(sec)
        return found

    for c in candidates:
        key = c.get("doi") or c.get("pmid") or c.get("title", "")
        if not key:
            continue
        priority = source_priority.get(c.get("source", ""), 2)
        if key not in seen:
            seen[key] = c
            continue
        existing = seen[key]
        existing_priority = source_priority.get(existing.get("source", ""), 2)
        winner, loser = (c, existing) if priority < existing_priority else (existing, c)
        merged_domains = _collect_domains(winner)
        for d in _collect_domains(loser):
            if d not in merged_domains:
                merged_domains.append(d)
        if merged_domains:
            winner = dict(winner)
            winner["primary_domain"] = merged_domains[0]
            winner["secondary_domains"] = merged_domains[1:]
        seen[key] = winner

    return list(seen.values())


def triage_all_commentary(commentary: list[dict], dry_run: bool) -> list[tuple[dict, CommentaryProposal | None]]:
    """Lightweight triage for editorials/letters/comments/news (no full agent)."""
    if not commentary:
        return []
    if dry_run or not ANTHROPIC_API_KEY:
        print(f"[Commentary] Skipping triage of {len(commentary)} commentary item(s) (dry run or no API key)")
        return []
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    kb = kb_papers(load_kb_data())
    results = []
    for c in commentary:
        print(f"[Commentary] {c.get('title', '')[:70]}")
        proposal = triage_commentary(client, c, kb, resolve_dois)
        target = proposal.target_id if proposal else None
        print(f"  → {target or 'no KB trial (tracked only)'}")
        results.append((c, proposal))
    return results


def publish_or_hold(
    classified: list[dict],
    today: str,
    dry_run: bool,
    *,
    max_repairs: int = MAX_REPAIR_ATTEMPTS,
) -> tuple[list[dict], list[dict]]:
    """Publish papers that pass the provenance gate, auto-repairing fixable failures up to max_repairs (ADR-0029)."""
    published, held = [], []
    client: Anthropic | None = None
    for paper in classified:
        reasons: list[str] = []
        ok = False
        for attempt in range(max_repairs + 1):
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
                    ok = True
                    break
                except PublishError as e:
                    reasons = e.reasons
            elif not reasons:
                ok = True
                break

            if attempt >= max_repairs or dry_run or not ANTHROPIC_API_KEY or not can_repair(paper, AUTO_PUBLISH_TOPICS):
                break

            if client is None:
                client = Anthropic(api_key=ANTHROPIC_API_KEY)
            title = paper.get("title", "")[:60]
            print(f"  [Repair] Attempt {attempt + 1}/{max_repairs} for {title}: {'; '.join(reasons)}")
            if not repair_paper(client, paper, reasons):
                break
            score = paper.get("ai_score")
            if isinstance(score, int) and score < RELEVANCE_THRESHOLD:
                reasons = [f"AI 重修後調降評分至 {score}/5（低於門檻 {RELEVANCE_THRESHOLD}）"]
                break

        if ok:
            paper["publish_status"] = "auto"
            published.append(paper)
        else:
            paper["gate_reasons"] = reasons
            paper["publish_status"] = "held"
            held.append(paper)
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
            revalidate_site()
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


def review_requested(pmids: list[str], topic: str, dry_run: bool = False) -> int:
    """Classify papers the maintainer names and open a review issue for each, whatever the score (#214).

    The scan never revisits a tracked paper, so this is the way back for one whose review
    issue failed to open, or one that scored under the threshold but belongs on the site.
    Nothing is published without review. Returns how many review issues were opened.
    """
    papers = efetch(pmids)
    missing = set(pmids) - {p["pmid"] for p in papers}
    if missing:
        print(f"[Review] Not found on PubMed: {', '.join(sorted(missing))}", file=sys.stderr)
    for p in papers:
        p.update(topic=topic, source="pubmed", maintainer_requested=True)
        p["abstract_status"] = abstract_status(p.get("abstract", ""))

    classify_all(papers, dry_run=dry_run)  # fills in each paper's score and entry in place
    for p in papers:
        score = p.get("ai_score")
        p["gate_reasons"] = [
            f"維護者指定送審（AI 評分 {score if score is not None else '—'}/5）",
            *evaluate_paper_gate(p, AUTO_PUBLISH_TOPICS).reasons,
        ]
    opened = create_issues(papers, dry_run=dry_run)
    if not dry_run:
        update_tracking(papers, [], date.today().isoformat())
    USAGE.report()
    return opened


def review_picks(dry_run: bool = False) -> bool:
    """Send the papers ticked on accepted digest issues to review (#218). Returns False if anything failed.

    A digest that fails keeps its label, so the next run tries it again.
    """
    digests = accepted_digests()
    if digests is None:
        print("[Digest] Could not list digest issues", file=sys.stderr)
        return False
    ok = True
    for issue in digests:
        picks = picked(issue["body"] or "")
        sent = sum(len(pmids) for pmids in picks.values())
        print(f"[Digest] #{issue['number']}: {sent} paper(s) ticked")
        try:
            opened = sum(review_requested(pmids, topic, dry_run=dry_run) for topic, pmids in picks.items())
        except Exception as e:  # one digest's failure should not stop the scan or the other digests
            print(f"[Digest] #{issue['number']} failed, will retry next run: {e}", file=sys.stderr)
            ok = False
            continue
        if not dry_run:
            finish(issue["number"], sent, opened)
    return ok


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

    # Commentary: lightweight triage. Items PubMed links to a KB trial pass the gate
    # and auto-publish; unverified items are skipped without opening review issues (ADR-0029).
    triaged = triage_all_commentary(commentary, dry_run)
    held_commentary = publish_or_hold_commentary(triaged, today_str, dry_run)
    if held_commentary:
        print(f"[Commentary] Skipped {len(held_commentary)} unverified commentary item(s) (auto-review mode)")

    # Layer 2: AI classification with topic-specific sub-agents
    print()
    classified = classify_all(research, dry_run=dry_run)
    print(f"[Pipeline] Papers passing relevance threshold: {len(classified)}")
    near_miss = [p for p in research if p.get("ai_score") == RELEVANCE_THRESHOLD - 1]
    if near_miss:
        print(f"[Pipeline] Skipped {len(near_miss)} score-{RELEVANCE_THRESHOLD - 1} paper(s) (no digest issue)")

    if classified:
        # Layer 3: papers passing the provenance gate (including up to 2 AI self-repair
        # passes) publish automatically; anything still unpublishable is logged and skipped (ADR-0029).
        published, held = publish_or_hold(classified, today_str, dry_run)
        print(f"\n[Pipeline] {len(published)} published, {len(held)} skipped after auto-review")
        for skipped in held:
            reasons = "; ".join(skipped.get("gate_reasons") or [])
            print(f"  [Skip] {skipped.get('title', '')[:80]} — {reasons}")
        if not dry_run and published:  # summary (I2 #191), auto news (K2 #252), and cache purge (K3 #253)
            summarize_new([p["kb_id"] for p in published if p.get("kb_id")])
            write_news_for_new(published, today=today_str)
            revalidate_site()

        # LINE notification for published high-relevance papers
        if published:
            print()
            notify_papers(published, dry_run=dry_run)
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
  python main.py --review 42811047 --topic generic-CRS  # Send a tracked paper to review again
        """,
    )
    parser.add_argument("--topic", help="Single topic to process (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Don't create issues or update tracking")
    parser.add_argument("--daily", action="store_true", help="Daily mode: only run during conference season")
    parser.add_argument("--bootstrap", action="store_true", help="Seed a new topic with 2-year PubMed history")
    parser.add_argument("--reldate", type=int, help="PubMed window in days for a one-off catch-up scan")
    parser.add_argument(
        "--review", nargs="+", metavar="PMID", help="Classify these papers and open a review issue for each"
    )
    args = parser.parse_args()

    if args.review:
        if not args.topic:
            parser.error("--review needs --topic")
        review_requested(args.review, args.topic, dry_run=args.dry_run)
        return

    # Before the scan, which returns early outside conference season on --daily days
    picks_ok = review_picks(dry_run=args.dry_run)
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
    if not picks_ok:
        print("[Pipeline] Exiting non-zero: a digest's picks were not sent to review.", file=sys.stderr)
    if journal_outage or not picks_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
