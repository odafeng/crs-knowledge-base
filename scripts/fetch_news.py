"""Layer 1d: Fetch conference coverage from medical news sites.

ASCO/ESMO meeting abstracts take weeks to months to reach PubMed.
Medical news sites publish same-day coverage. This module searches
them during conference season to close the gap.

Sources:
- ASCO Post (ascopost.com)
- OncLive (onclive.com)
- Medscape Oncology (medscape.com)
- Cancer Network (cancernetwork.com)
"""

import json
import re
import sys
import time
from datetime import datetime

from config import load_queries, load_tracked_dois


NEWS_SOURCES = [
    {
        "name": "ASCO Post",
        "search_url": "https://ascopost.com/?s={query}",
        "domain": "ascopost.com",
    },
    {
        "name": "OncLive",
        "search_url": "https://www.onclive.com/search?q={query}",
        "domain": "onclive.com",
    },
    {
        "name": "Cancer Network",
        "search_url": "https://www.cancernetwork.com/search?q={query}",
        "domain": "cancernetwork.com",
    },
]


def _playwright_available():
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def _scrape_news_site(search_url: str, source_name: str) -> list[dict]:
    """Scrape search results from a medical news site via Playwright."""
    from playwright.sync_api import sync_playwright

    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(search_url, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)

            # Generic: find article links with titles
            links = page.locator("a[href]")
            count = links.count()

            for i in range(min(count, 20)):
                try:
                    el = links.nth(i)
                    href = el.get_attribute("href") or ""
                    text = el.inner_text().strip()

                    # Filter: must look like an article (not nav, not ad)
                    if len(text) < 30 or len(text) > 300:
                        continue
                    if not href or href == "#":
                        continue
                    # Skip non-article links
                    skip_patterns = ["login", "subscribe", "about", "contact", "privacy", "terms", "search", "tag", "category"]
                    if any(p in href.lower() for p in skip_patterns):
                        continue

                    results.append({
                        "title": text,
                        "link": href if href.startswith("http") else f"https://{source_name.lower().replace(' ', '')}.com{href}",
                        "source_name": source_name,
                    })
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        print(f"    [WARN] {source_name} scrape failed: {e}", file=sys.stderr)

    return results


def fetch_news(topic: str | None = None, dry_run: bool = False) -> list[dict]:
    """Fetch conference coverage from medical news sites.

    Only runs during conference season. Returns candidate dicts.
    """
    if not _playwright_available():
        print("[News] Playwright not installed. Skipping news search.", file=sys.stderr)
        return []

    queries_data = load_queries()
    tracked = load_tracked_dois()
    tracked_doi_set = set(tracked.keys())

    topics_config = {k: v for k, v in queries_data.items() if k not in ("rss_feeds", "conference_seasons")}
    if topic:
        topics_config = {k: v for k, v in topics_config.items() if k == topic}

    candidates = []
    seen_titles = set()

    for t, cfg in topics_config.items():
        keywords = cfg.get("keywords", [])[:3]  # Top 3 keywords per topic
        if not keywords:
            continue

        for kw in keywords:
            # Build conference-specific search query
            search_query = f"ASCO 2026 {kw}" if "ASCO" in str(queries_data.get("conference_seasons", {})) else kw

            for source in NEWS_SOURCES:
                url = source["search_url"].format(query=search_query.replace(" ", "+"))
                print(f"  [{source['name']}] {search_query}")

                articles = _scrape_news_site(url, source["name"])

                for art in articles:
                    title = art["title"]
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)

                    candidates.append({
                        "pmid": "",
                        "doi": "",
                        "title": title,
                        "authors": "",
                        "journal": f"{source['name']} (conference coverage)",
                        "year": str(datetime.now().year),
                        "abstract": "",
                        "topic": t,
                        "source": "news",
                        "link": art["link"],
                    })

                time.sleep(1)

    if dry_run:
        print(f"\n[DRY RUN] News candidates: {len(candidates)}")
        for c in candidates[:10]:
            print(f"  [{c['topic']}] {c['source']}: {c['title'][:80]}")

    return candidates
