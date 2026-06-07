"""Layer 1c: Fetch new abstracts from ASCO/ESMO via headless Playwright.

ASCO uses a Flutter SPA and ESMO uses bot protection, so plain HTTP
requests don't work. Playwright renders the pages in headless Chromium.

Falls back gracefully if Playwright is not installed (e.g., local dev
without it) — the pipeline continues with PubMed + RSS only.
"""

import argparse
import json
import re
import sys
import time

from config import load_queries, load_tracked_abstracts, load_tracked_dois


def _playwright_available():
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def _scrape_asco(search_terms):
    """Scrape ASCO abstract search results via Playwright."""
    from playwright.sync_api import sync_playwright

    candidates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for term in search_terms:
            print(f"  [ASCO] Searching: {term}")
            try:
                url = f"https://meetings.asco.org/abstracts-presentations/search?q={term}"
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)  # Let Flutter render

                # Try to find abstract entries
                # ASCO Flutter app renders abstract cards — extract text content
                entries = page.locator('[class*="abstract"], [class*="search-result"], a[href*="/abstracts-presentations/"]')
                count = entries.count()

                for i in range(min(count, 10)):
                    try:
                        el = entries.nth(i)
                        text = el.inner_text()
                        href = el.get_attribute("href") or ""

                        if not text or len(text) < 20:
                            continue

                        # Extract abstract ID from URL
                        aid_match = re.search(r'/(\d+)', href)
                        aid = aid_match.group(1) if aid_match else f"asco-{i}"

                        # Parse title (usually first line) and authors
                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        title = lines[0] if lines else text[:200]
                        authors = lines[1] if len(lines) > 1 else ""

                        candidates.append({
                            "abstract_id": f"asco-2026-{aid}",
                            "title": title[:300],
                            "authors": authors[:200],
                            "journal": "ASCO 2026",
                            "year": "2026",
                            "abstract": " ".join(lines[2:])[:500] if len(lines) > 2 else "",
                            "doi": "",
                            "pmid": "",
                            "topic": "",
                            "source": "asco",
                            "link": f"https://meetings.asco.org{href}" if href.startswith("/") else href,
                        })
                    except Exception:
                        continue

            except Exception as e:
                print(f"    [WARN] ASCO search failed for '{term}': {e}", file=sys.stderr)

            time.sleep(2)

        browser.close()

    return candidates


def _scrape_esmo(search_terms):
    """Scrape ESMO abstract search results via Playwright."""
    from playwright.sync_api import sync_playwright

    candidates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for term in search_terms:
            print(f"  [ESMO] Searching: {term}")
            try:
                url = f"https://oncologypro.esmo.org/meeting-resources?q={term}&type=abstract"
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                entries = page.locator('a[href*="abstract"], [class*="search-result"], [class*="abstract-card"]')
                count = entries.count()

                for i in range(min(count, 10)):
                    try:
                        el = entries.nth(i)
                        text = el.inner_text()
                        href = el.get_attribute("href") or ""

                        if not text or len(text) < 20:
                            continue

                        aid_match = re.search(r'/abstract/(\d+)', href)
                        aid = aid_match.group(1) if aid_match else f"esmo-{i}"

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        title = lines[0] if lines else text[:200]

                        candidates.append({
                            "abstract_id": f"esmo-{aid}",
                            "title": title[:300],
                            "authors": "",
                            "journal": "ESMO",
                            "year": "",
                            "abstract": "",
                            "doi": "",
                            "pmid": "",
                            "topic": "",
                            "source": "esmo",
                            "link": f"https://oncologypro.esmo.org{href}" if href.startswith("/") else href,
                        })
                    except Exception:
                        continue

            except Exception as e:
                print(f"    [WARN] ESMO search failed for '{term}': {e}", file=sys.stderr)

            time.sleep(2)

        browser.close()

    return candidates


def _scrape_ascrs(search_terms):
    """Scrape ASCRS abstract search results via Playwright."""
    from playwright.sync_api import sync_playwright

    candidates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for term in search_terms:
            print(f"  [ASCRS] Searching: {term}")
            try:
                url = f"https://www.fascrs.org/search?q={term}"
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                entries = page.locator('a[href*="abstract"], [class*="search-result"], [class*="views-row"]')
                count = entries.count()

                for i in range(min(count, 10)):
                    try:
                        el = entries.nth(i)
                        text = el.inner_text()
                        href = el.get_attribute("href") or ""

                        if not text or len(text) < 20:
                            continue

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        title = lines[0] if lines else text[:200]

                        candidates.append({
                            "abstract_id": f"ascrs-{i}-{hash(title) % 10000}",
                            "title": title[:300],
                            "authors": "",
                            "journal": "ASCRS",
                            "year": "",
                            "abstract": "",
                            "doi": "",
                            "pmid": "",
                            "topic": "",
                            "source": "ascrs",
                            "link": f"https://www.fascrs.org{href}" if href.startswith("/") else href,
                        })
                    except Exception:
                        continue

            except Exception as e:
                print(f"    [WARN] ASCRS search failed for '{term}': {e}", file=sys.stderr)

            time.sleep(2)

        browser.close()

    return candidates


def _scrape_escp(search_terms):
    """Scrape ESCP abstract search results via Playwright."""
    from playwright.sync_api import sync_playwright

    candidates = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for term in search_terms:
            print(f"  [ESCP] Searching: {term}")
            try:
                url = f"https://www.escp.eu.com/search?q={term}"
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)

                entries = page.locator('a[href*="abstract"], [class*="search-result"], [class*="views-row"]')
                count = entries.count()

                for i in range(min(count, 10)):
                    try:
                        el = entries.nth(i)
                        text = el.inner_text()
                        href = el.get_attribute("href") or ""

                        if not text or len(text) < 20:
                            continue

                        lines = [l.strip() for l in text.split("\n") if l.strip()]
                        title = lines[0] if lines else text[:200]

                        candidates.append({
                            "abstract_id": f"escp-{i}-{hash(title) % 10000}",
                            "title": title[:300],
                            "authors": "",
                            "journal": "ESCP",
                            "year": "",
                            "abstract": "",
                            "doi": "",
                            "pmid": "",
                            "topic": "",
                            "source": "escp",
                            "link": f"https://www.escp.eu.com{href}" if href.startswith("/") else href,
                        })
                    except Exception:
                        continue

            except Exception as e:
                print(f"    [WARN] ESCP search failed for '{term}': {e}", file=sys.stderr)

            time.sleep(2)

        browser.close()

    return candidates


def fetch_conferences(topic=None, dry_run=False):
    """Fetch new conference abstracts. Returns list of candidate dicts."""
    if not _playwright_available():
        print("[Conferences] Playwright not installed. Skipping conference scraping.", file=sys.stderr)
        print("  Install: pip install playwright && playwright install chromium", file=sys.stderr)
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

    # ASCRS/ESCP cover all colorectal surgery — use terms from ALL topics
    all_terms = set()
    for cfg in topics_config.values():
        all_terms.update(cfg.get("conference_terms", []))

    print(f"[Conferences] ASCRS/ESCP: searching {len(all_terms)} terms across all topics")
    ascrs_results = _scrape_ascrs(list(all_terms)[:8])  # Limit to avoid over-scraping
    escp_results = _scrape_escp(list(all_terms)[:8])

    for t, cfg in topics_config.items():
        terms = cfg.get("conference_terms", [])
        if not terms:
            continue

        # ASCO/ESMO: per-topic search (oncology-focused)
        print(f"[Conferences] Topic: {t} (ASCO/ESMO)")
        asco = _scrape_asco(terms)
        esmo = _scrape_esmo(terms)

        for c in asco + esmo:
            if c["abstract_id"] in tracked_ids:
                continue
            if c["doi"] and c["doi"] in tracked_doi_set:
                continue
            c["topic"] = t
            all_candidates.append(c)

    # ASCRS/ESCP results: assign topic by keyword matching
    for c in ascrs_results + escp_results:
        if c["abstract_id"] in tracked_ids:
            continue
        if c["doi"] and c["doi"] in tracked_doi_set:
            continue
        title_lower = c.get("title", "").lower()
        # Match to best topic by keywords
        assigned = False
        for t, cfg in topics_config.items():
            keywords = cfg.get("keywords", [])
            if any(kw.lower() in title_lower for kw in keywords):
                c["topic"] = t
                all_candidates.append(c)
                assigned = True
                break
        if not assigned:
            # Default surgical abstracts to robotic-surgery
            c["topic"] = "robotic-surgery"
            all_candidates.append(c)

    if dry_run:
        print(f"\n[DRY RUN] Conference candidates: {len(all_candidates)}")
        for c in all_candidates:
            print(f"  [{c['topic']}] {c['source'].upper()}: {c['title'][:80]}")

    return all_candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch conference abstracts via Playwright")
    parser.add_argument("--topic", help="Single topic (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = fetch_conferences(topic=args.topic, dry_run=args.dry_run)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
