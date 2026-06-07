"""Layer 1c: Fetch new abstracts from ASCO/ESMO/ASCRS/ESCP via headless Playwright.

These conference sites use JS rendering or bot protection that blocks plain HTTP.
A single generic scraper handles all four — differences are just URL pattern and source name.
"""

import hashlib
import json
import re
import sys
import time

from config import load_queries, load_tracked_abstracts, load_tracked_dois


def _stable_id(prefix: str, text: str) -> str:
    """Generate a deterministic ID from prefix + text content."""
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _playwright_available():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except ImportError:
        return False


# Conference scraping configurations
CONFERENCE_CONFIGS = [
    {
        "key": "asco",
        "name": "ASCO",
        "search_url": "https://meetings.asco.org/abstracts-presentations/search?q={query}",
        "selectors": '[class*="abstract"], [class*="search-result"], a[href*="/abstracts-presentations/"]',
        "id_pattern": r"/(\d+)",
        "id_prefix": "asco-2026",
    },
    {
        "key": "esmo",
        "name": "ESMO",
        "search_url": "https://oncologypro.esmo.org/meeting-resources?q={query}&type=abstract",
        "selectors": 'a[href*="abstract"], [class*="search-result"], [class*="abstract-card"]',
        "id_pattern": r"/abstract/(\d+)",
        "id_prefix": "esmo",
    },
    {
        "key": "ascrs",
        "name": "ASCRS",
        "search_url": "https://www.fascrs.org/search?q={query}",
        "selectors": 'a[href*="abstract"], [class*="search-result"], [class*="views-row"]',
        "id_pattern": None,
        "id_prefix": "ascrs",
    },
    {
        "key": "escp",
        "name": "ESCP",
        "search_url": "https://www.escp.eu.com/search?q={query}",
        "selectors": 'a[href*="abstract"], [class*="search-result"], [class*="views-row"]',
        "id_pattern": None,
        "id_prefix": "escp",
    },
]


def _scrape_conference(config: dict, search_terms: list[str]) -> list[dict]:
    """Generic conference scraper using Playwright."""
    from playwright.sync_api import sync_playwright

    candidates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for term in search_terms:
            print(f"  [{config['name']}] Searching: {term}")
            try:
                url = config["search_url"].format(query=term)
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                entries = page.locator(config["selectors"])
                count = entries.count()

                for i in range(min(count, 10)):
                    try:
                        el = entries.nth(i)
                        text = el.inner_text()
                        href = el.get_attribute("href") or ""

                        if not text or len(text) < 20:
                            continue

                        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                        title = lines[0] if lines else text[:200]

                        if config["id_pattern"]:
                            aid_match = re.search(config["id_pattern"], href)
                            aid = (
                                f"{config['id_prefix']}-{aid_match.group(1)}"
                                if aid_match
                                else _stable_id(config["id_prefix"], title)
                            )
                        else:
                            aid = _stable_id(config["id_prefix"], title)

                        candidates.append(
                            {
                                "abstract_id": aid,
                                "title": title[:300],
                                "authors": lines[1][:200] if len(lines) > 1 else "",
                                "journal": config["name"],
                                "year": "",
                                "abstract": " ".join(lines[2:])[:500] if len(lines) > 2 else "",
                                "doi": "",
                                "pmid": "",
                                "topic": "",
                                "source": config["key"],
                                "link": href if href.startswith("http") else "",
                            }
                        )
                    except Exception:
                        continue

            except Exception as e:
                print(f"    [WARN] {config['name']} search failed for '{term}': {e}", file=sys.stderr)

            time.sleep(2)

        browser.close()

    return candidates


def fetch_conferences(topic=None, dry_run=False):
    """Fetch new conference abstracts. Returns list of candidate dicts."""
    if not _playwright_available():
        print("[Conferences] Playwright not installed. Skipping.", file=sys.stderr)
        return []

    queries = load_queries()
    tracked_abstracts = load_tracked_abstracts()
    tracked_dois = load_tracked_dois()
    tracked_ids = set(tracked_abstracts.keys())
    tracked_doi_set = set(tracked_dois.keys())

    topics_config = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}
    if topic:
        topics_config = {k: v for k, v in topics_config.items() if k == topic}

    all_candidates = []

    # ASCRS/ESCP: search all topics (colorectal surgery covers everything)
    all_terms = set()
    for cfg in topics_config.values():
        all_terms.update(cfg.get("conference_terms", []))

    surgical_configs = [c for c in CONFERENCE_CONFIGS if c["key"] in ("ascrs", "escp")]
    oncology_configs = [c for c in CONFERENCE_CONFIGS if c["key"] in ("asco", "esmo")]

    print(f"[Conferences] ASCRS/ESCP: searching {len(all_terms)} terms across all topics")
    ascrs_escp_results = []
    for conf in surgical_configs:
        ascrs_escp_results.extend(_scrape_conference(conf, list(all_terms)[:8]))

    # ASCO/ESMO: per-topic search
    for t, cfg in topics_config.items():
        terms = cfg.get("conference_terms", [])
        if not terms:
            continue

        print(f"[Conferences] Topic: {t} (ASCO/ESMO)")
        for conf in oncology_configs:
            results = _scrape_conference(conf, terms)
            for c in results:
                if c["abstract_id"] in tracked_ids:
                    continue
                if c["doi"] and c["doi"] in tracked_doi_set:
                    continue
                c["topic"] = t
                all_candidates.append(c)

    # ASCRS/ESCP: assign topic by keyword matching
    for c in ascrs_escp_results:
        if c["abstract_id"] in tracked_ids:
            continue
        title_lower = c.get("title", "").lower()
        assigned = False
        for t, cfg in topics_config.items():
            keywords = cfg.get("keywords", [])
            if any(kw.lower() in title_lower for kw in keywords):
                c["topic"] = t
                all_candidates.append(c)
                assigned = True
                break
        if not assigned:
            c["topic"] = "robotic-surgery"
            all_candidates.append(c)

    if dry_run:
        print(f"\n[DRY RUN] Conference candidates: {len(all_candidates)}")
        for c in all_candidates[:10]:
            print(f"  [{c['topic']}] {c['source'].upper()}: {c['title'][:80]}")

    return all_candidates


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fetch conference abstracts via Playwright")
    parser.add_argument("--topic", help="Single topic (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = fetch_conferences(topic=args.topic, dry_run=args.dry_run)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
