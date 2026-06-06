"""Layer 1b: Fetch new papers from journal RSS feeds."""

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from config import load_queries, load_tracked_dois


def _fetch_feed(url, timeout=20):
    """Fetch and parse an RSS/Atom feed. Returns list of entry dicts."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CRS-KB-PaperWatch/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [WARN] Failed to fetch {url}: {e}", file=sys.stderr)
        return []

    entries = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        print(f"  [WARN] Failed to parse XML from {url}", file=sys.stderr)
        return []

    # Handle RSS 2.0
    for item in root.findall(".//item"):
        entry = {
            "title": item.findtext("title", ""),
            "link": item.findtext("link", ""),
            "description": item.findtext("description", ""),
            "pub_date": item.findtext("pubDate", ""),
        }
        # Try to extract DOI from link or dc:identifier
        doi = _extract_doi(entry["link"]) or _extract_doi(entry.get("description", ""))
        entry["doi"] = doi
        entries.append(entry)

    # Handle Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.findall(".//atom:entry", ns):
        link_elem = item.find("atom:link[@rel='alternate']", ns) or item.find("atom:link", ns)
        link = link_elem.get("href", "") if link_elem is not None else ""
        entry = {
            "title": item.findtext("atom:title", "", ns),
            "link": link,
            "description": item.findtext("atom:summary", "", ns),
            "pub_date": item.findtext("atom:published", "", ns) or item.findtext("atom:updated", "", ns),
        }
        entry["doi"] = _extract_doi(link) or _extract_doi(entry["description"])
        entries.append(entry)

    return entries


def _extract_doi(text):
    """Extract DOI from text or URL."""
    if not text:
        return ""
    m = re.search(r"(10\.\d{4,}/[^\s<>\"]+)", text)
    return m.group(1).rstrip(".,;") if m else ""


def _matches_topic(entry, filter_terms):
    """Check if an RSS entry matches any of the filter terms."""
    text = (entry.get("title", "") + " " + entry.get("description", "")).lower()
    return any(term.lower() in text for term in filter_terms)


def fetch_rss(topic=None, dry_run=False):
    """Fetch new papers from RSS feeds. Returns list of candidate dicts."""
    queries = load_queries()
    tracked = load_tracked_dois()
    tracked_doi_set = set(tracked.keys())
    feeds = queries.get("rss_feeds", [])
    topics_config = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}

    if topic:
        topics_config = {k: v for k, v in topics_config.items() if k == topic}

    candidates = []
    seen_dois = set()

    for feed in feeds:
        print(f"[RSS] Fetching {feed['name']} ...")
        entries = _fetch_feed(feed["url"])
        print(f"  Got {len(entries)} entries")
        time.sleep(0.3)

        for entry in entries:
            doi = entry.get("doi", "")
            if doi and (doi in tracked_doi_set or doi in seen_dois):
                continue

            for t, cfg in topics_config.items():
                if _matches_topic(entry, cfg.get("rss_filter_terms", [])):
                    candidate = {
                        "pmid": "",
                        "doi": doi,
                        "title": entry["title"],
                        "authors": "",
                        "journal": feed["name"],
                        "year": str(datetime.now().year),
                        "abstract": entry.get("description", "")[:500],
                        "topic": t,
                        "source": "rss",
                        "link": entry.get("link", ""),
                    }
                    candidates.append(candidate)
                    if doi:
                        seen_dois.add(doi)
                    break  # one topic per entry

    if dry_run:
        print(f"\n[DRY RUN] RSS candidates: {len(candidates)}")
        for c in candidates:
            print(f"  [{c['topic']}] {c['journal']}: {c['title'][:80]}")

    return candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch new papers from RSS feeds")
    parser.add_argument("--topic", help="Single topic to filter (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = fetch_rss(topic=args.topic, dry_run=args.dry_run)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
