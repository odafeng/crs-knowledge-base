"""Quarterly refresh of conference dates from official websites.

Scrapes each conference's official page for the next meeting dates,
then updates queries.json with precise start/end windows (±2 weeks buffer).

Usage:
  python scripts/refresh_conference_dates.py           # refresh all
  python scripts/refresh_conference_dates.py --dry-run  # print only
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

QUERIES_FILE = Path(__file__).resolve().parent / "queries.json"

# Month name → number mapping
MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}

BUFFER_DAYS = 14  # ±2 weeks around actual dates


def _extract_dates_from_text(text: str, year: int | None = None) -> list[tuple[int, int]]:
    """Extract (month, day) pairs from text like 'January 23-25, 2027' or 'Sep 12 - Oct 3'.

    Returns list of (month, day) tuples found.
    """
    if year is None:
        year = datetime.now().year

    results = []

    # Pattern: "Month DD-DD, YYYY" or "Month DD – DD, YYYY"
    pattern1 = r"(\w+)\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})\s*,?\s*(\d{4})?"
    for m in re.finditer(pattern1, text, re.IGNORECASE):
        month_str, day1, day2, yr = m.groups()
        month_num = MONTHS.get(month_str.lower())
        if month_num:
            results.append((month_num, int(day1)))
            results.append((month_num, int(day2)))

    # Pattern: "Month DD - Month DD" (cross-month)
    pattern2 = r"(\w+)\s+(\d{1,2})\s*[-–—]\s*(\w+)\s+(\d{1,2})\s*,?\s*(\d{4})?"
    for m in re.finditer(pattern2, text, re.IGNORECASE):
        m1, d1, m2, d2, yr = m.groups()
        mn1 = MONTHS.get(m1.lower())
        mn2 = MONTHS.get(m2.lower())
        if mn1 and mn2:
            results.append((mn1, int(d1)))
            results.append((mn2, int(d2)))

    # Pattern: "DD-DD Month YYYY" (European style)
    pattern3 = r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+(\w+)\s*,?\s*(\d{4})?"
    for m in re.finditer(pattern3, text, re.IGNORECASE):
        d1, d2, month_str, yr = m.groups()
        month_num = MONTHS.get(month_str.lower())
        if month_num:
            results.append((month_num, int(d1)))
            results.append((month_num, int(d2)))

    return results


def _dates_to_window(dates: list[tuple[int, int]], buffer_days: int = BUFFER_DAYS) -> tuple[str, str] | None:
    """Convert extracted dates to a start-end window string (MM-DD format) with buffer."""
    if not dates:
        return None

    year = datetime.now().year
    dt_list = []
    for month, day in dates:
        try:
            dt_list.append(datetime(year, month, min(day, 28)))
        except ValueError:
            continue

    if not dt_list:
        return None

    earliest = min(dt_list) - timedelta(days=buffer_days)
    latest = max(dt_list) + timedelta(days=buffer_days)

    return earliest.strftime("%m-%d"), latest.strftime("%m-%d")


def _fetch_page_text(url: str) -> str:
    """Fetch a page and return stripped text content."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            page.wait_for_timeout(2000)
            text = page.locator("body").inner_text()
            browser.close()
            return text
    except ImportError:
        # Fallback to urllib
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", html)
            return re.sub(r"\s+", " ", text)
        except Exception as e:
            print(f"  [WARN] Failed to fetch {url}: {e}", file=sys.stderr)
            return ""


def refresh_dates(dry_run: bool = False) -> bool:
    """Scrape conference websites and update queries.json."""
    with open(QUERIES_FILE) as f:
        queries = json.load(f)

    seasons = queries.get("conference_seasons", {})
    updated = False
    next_year = datetime.now().year + 1

    for key, conf in seasons.items():
        url = conf.get("url", "")
        if not url:
            continue

        print(f"[Dates] {conf['name']}...")
        text = _fetch_page_text(url)
        if not text:
            print(f"  Could not fetch page")
            continue

        # Look for dates mentioning next year or current year
        dates = _extract_dates_from_text(text, next_year)
        if not dates:
            dates = _extract_dates_from_text(text, datetime.now().year)

        if not dates:
            print(f"  No dates found on page")
            continue

        window = _dates_to_window(dates)
        if not window:
            print(f"  Could not parse date window")
            continue

        new_start, new_end = window
        old_start, old_end = conf["start"], conf["end"]

        if new_start != old_start or new_end != old_end:
            print(f"  Updated: {old_start}~{old_end} → {new_start}~{new_end}")
            if not dry_run:
                conf["start"] = new_start
                conf["end"] = new_end
                updated = True
        else:
            print(f"  No change: {old_start}~{old_end}")

    if updated:
        with open(QUERIES_FILE, "w") as f:
            json.dump(queries, f, indent=2, ensure_ascii=False)
        print(f"\n[Dates] Updated queries.json")

    return updated


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Refresh conference dates from official websites")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    refresh_dates(dry_run=args.dry_run)
