"""Layer 1c: Fetch new abstracts from ASCO/ESMO conference sites."""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

from config import load_queries, load_tracked_abstracts, load_tracked_dois


def _http_get_json(url, timeout=20):
    """GET request returning parsed JSON, or None on failure."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "CRS-KB-PaperWatch/1.0",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [WARN] Request failed: {url} — {e}", file=sys.stderr)
        return None


def _http_get_html(url, timeout=20):
    """GET request returning HTML string, or empty string on failure."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "CRS-KB-PaperWatch/1.0",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Request failed: {url} — {e}", file=sys.stderr)
        return ""


def fetch_asco_abstracts(search_terms):
    """Search ASCO meeting abstracts. Returns list of candidate dicts."""
    candidates = []
    base_url = "https://meetings.asco.org/api/search"

    for term in search_terms:
        print(f"  [ASCO] Searching: {term}")
        params = urllib.parse.urlencode({"q": term, "type": "abstract", "limit": 20})
        url = f"{base_url}?{params}"
        data = _http_get_json(url)

        if not data or "results" not in data:
            # Fallback: try HTML scraping
            html_url = f"https://meetings.asco.org/abstracts-presentations/search?q={urllib.parse.quote(term)}"
            html = _http_get_html(html_url)
            if html:
                # Extract abstract IDs from HTML
                abstract_ids = re.findall(r'/abstract/(\d+)', html)
                for aid in abstract_ids[:10]:
                    candidates.append({
                        "abstract_id": f"asco-{aid}",
                        "title": f"ASCO Abstract #{aid}",
                        "authors": "",
                        "journal": "ASCO",
                        "year": "",
                        "abstract": "",
                        "doi": "",
                        "pmid": "",
                        "topic": "",
                        "source": "asco",
                        "link": f"https://meetings.asco.org/abstracts-presentations/{aid}",
                    })
            continue

        for result in data.get("results", []):
            candidates.append({
                "abstract_id": f"asco-{result.get('id', '')}",
                "title": result.get("title", ""),
                "authors": result.get("authors", ""),
                "journal": "ASCO",
                "year": str(result.get("year", "")),
                "abstract": result.get("abstract", "")[:1000],
                "doi": result.get("doi", ""),
                "pmid": "",
                "topic": "",
                "source": "asco",
                "link": result.get("url", ""),
            })

        time.sleep(0.5)

    return candidates


def fetch_esmo_abstracts(search_terms):
    """Search ESMO abstracts. Returns list of candidate dicts."""
    candidates = []
    base_url = "https://oncologypro.esmo.org"

    for term in search_terms:
        print(f"  [ESMO] Searching: {term}")
        search_url = f"{base_url}/search?q={urllib.parse.quote(term)}&type=abstract"
        html = _http_get_html(search_url)

        if not html:
            continue

        # Extract abstract links
        links = re.findall(r'href="(/abstract[^"]*)"', html)
        titles = re.findall(r'class="search-result-title[^"]*">([^<]+)<', html)

        for i, link in enumerate(links[:10]):
            title = titles[i] if i < len(titles) else f"ESMO Abstract"
            abstract_id = re.search(r'/abstract/(\d+)', link)
            aid = abstract_id.group(1) if abstract_id else link.split("/")[-1]

            candidates.append({
                "abstract_id": f"esmo-{aid}",
                "title": title.strip(),
                "authors": "",
                "journal": "ESMO",
                "year": "",
                "abstract": "",
                "doi": "",
                "pmid": "",
                "topic": "",
                "source": "esmo",
                "link": f"{base_url}{link}",
            })

        time.sleep(0.5)

    return candidates


def fetch_conferences(topic=None, dry_run=False):
    """Fetch new conference abstracts. Returns list of candidate dicts."""
    queries = load_queries()
    tracked_abstracts = load_tracked_abstracts()
    tracked_dois = load_tracked_dois()
    tracked_ids = set(tracked_abstracts.keys())
    tracked_doi_set = set(tracked_dois.keys())

    topics_config = {k: v for k, v in queries.items() if k not in ("rss_feeds", "conference_seasons")}
    if topic:
        topics_config = {k: v for k, v in topics_config.items() if k == topic}

    all_candidates = []

    for t, cfg in topics_config.items():
        terms = cfg.get("conference_terms", [])
        if not terms:
            continue

        print(f"[Conferences] Topic: {t}")
        asco = fetch_asco_abstracts(terms)
        esmo = fetch_esmo_abstracts(terms)

        for c in asco + esmo:
            # Dedup
            if c["abstract_id"] in tracked_ids:
                continue
            if c["doi"] and c["doi"] in tracked_doi_set:
                continue
            c["topic"] = t
            all_candidates.append(c)

    if dry_run:
        print(f"\n[DRY RUN] Conference candidates: {len(all_candidates)}")
        for c in all_candidates:
            print(f"  [{c['topic']}] {c['source'].upper()}: {c['title'][:80]}")

    return all_candidates


def main():
    parser = argparse.ArgumentParser(description="Fetch conference abstracts")
    parser.add_argument("--topic", help="Single topic (default: all)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidates = fetch_conferences(topic=args.topic, dry_run=args.dry_run)

    if not args.dry_run:
        json.dump(candidates, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
