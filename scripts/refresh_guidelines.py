"""Refresh guideline cache by querying OpenEvidence via headless Playwright.

Fully automated — runs in GitHub Actions without a real browser.
Uses stored cookies (OE_COOKIES_JSON secret) to maintain session.

Usage:
  python scripts/refresh_guidelines.py                              # all topics
  python scripts/refresh_guidelines.py --topic mCRC-BRAF-V600E      # single topic
  python scripts/refresh_guidelines.py --export-cookies              # login + export cookies
"""

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

GUIDELINES_DIR = Path(__file__).resolve().parent.parent / "data" / "guidelines"
OE_BASE_URL = "https://www.openevidence.com"
OE_COOKIES_JSON = os.environ.get("OE_COOKIES_JSON", "")

TOPIC_QUESTIONS = {
    "mCRC-BRAF-V600E": "What are the current ASCO and NCCN guideline recommendations for treatment of BRAF V600E mutant metastatic colorectal cancer? Include first-line and second-line recommendations, and note any recent updates from BREAKWATER trial data.",
    "mCRC-KRAS-G12C": "What are the current ASCO and NCCN guideline recommendations for KRAS G12C mutant metastatic colorectal cancer? Include approved agents (sotorasib, adagrasib) and recommended combinations with anti-EGFR.",
    "mCRC-MSI-H": "What are the current ASCO and NCCN guideline recommendations for MSI-H/dMMR colorectal cancer? Cover both metastatic (first-line immunotherapy) and localized settings (neoadjuvant immunotherapy, non-operative management for rectal cancer).",
    "mCRC-HER2": "What are the current NCCN guideline recommendations for HER2-amplified metastatic colorectal cancer? Include approved regimens (tucatinib+trastuzumab, trastuzumab deruxtecan) and testing recommendations.",
    "mCRC-RAS-wt": "What are the current ASCO and NCCN guideline recommendations for RAS wild-type metastatic colorectal cancer regarding anti-EGFR therapy? Cover first-line selection (cetuximab vs bevacizumab), tumor sidedness, maintenance therapy, and rechallenge strategies.",
    "robotic-surgery": "What are the current guidelines and consensus statements regarding robotic surgery for rectal cancer (robotic TME)? Include evidence from REAL trial and recommendations from ESCP, ASCRS, or other surgical societies.",
}


def _load_cookies():
    """Load cookies from env var or local file."""
    if OE_COOKIES_JSON:
        try:
            return json.loads(OE_COOKIES_JSON)
        except json.JSONDecodeError:
            pass

    cookie_file = Path.home() / ".openevidence-mcp" / "auth" / "cookies.json"
    if cookie_file.exists():
        try:
            with open(cookie_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    return None


def _query_oe_playwright(question, cookies):
    """Query OpenEvidence using headless Playwright with session cookies."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Load cookies into browser context
        if cookies:
            playwright_cookies = []
            for c in cookies:
                cookie = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".openevidence.com"),
                    "path": c.get("path", "/"),
                }
                if cookie["name"] and cookie["value"]:
                    playwright_cookies.append(cookie)
            if playwright_cookies:
                context.add_cookies(playwright_cookies)

        page = context.new_page()

        # Navigate to OE and submit question
        page.goto(f"{OE_BASE_URL}/search", wait_until="networkidle", timeout=30000)

        # Type question into search box
        search_input = page.locator('textarea, input[type="text"], [role="textbox"]').first
        search_input.fill(question)
        search_input.press("Enter")

        # Wait for answer to generate (OE takes time)
        page.wait_for_timeout(5000)

        # Wait for the answer content to appear
        try:
            page.wait_for_selector('[class*="answer"], [class*="response"], [class*="article-content"], main article', timeout=120000)
            page.wait_for_timeout(3000)  # Let it finish rendering
        except Exception:
            pass

        # Extract answer text
        answer = ""
        for selector in ['[class*="answer"]', '[class*="response"]', 'main article', '[class*="article-content"]', '.prose']:
            elements = page.locator(selector)
            if elements.count() > 0:
                answer = elements.first.inner_text()
                if len(answer) > 100:
                    break

        if not answer:
            # Fallback: grab all main content
            answer = page.locator("main").inner_text() if page.locator("main").count() > 0 else ""

        # Extract citations if visible
        citations = []
        cite_elements = page.locator('[class*="citation"], [class*="reference"], [class*="source"]')
        for i in range(min(cite_elements.count(), 10)):
            text = cite_elements.nth(i).inner_text()
            if text.strip():
                citations.append(text.strip())

        browser.close()

        return {
            "answer": answer[:5000],
            "citations": citations[:10],
        }


def export_cookies():
    """Interactive login to OpenEvidence, then export cookies."""
    from playwright.sync_api import sync_playwright

    print("[OE] Opening browser for login...")
    print("  Please log in to OpenEvidence, then press Enter here when done.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # Visible browser for login
        context = browser.new_context()
        page = context.new_page()
        page.goto(OE_BASE_URL, wait_until="networkidle")

        input("\n  Press Enter after logging in to OpenEvidence...\n")

        cookies = context.cookies()
        browser.close()

    # Save cookies
    cookie_dir = Path.home() / ".openevidence-mcp" / "auth"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = cookie_dir / "cookies.json"
    with open(cookie_file, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"[OE] Saved {len(cookies)} cookies to {cookie_file}")
    print(f"\n  For GitHub Actions, run:")
    print(f"  cat {cookie_file} | gh secret set OE_COOKIES_JSON")

    return cookies


def refresh(topics=None):
    """Refresh guideline cache for specified topics."""
    cookies = _load_cookies()
    if not cookies:
        print("[WARN] No OE cookies found. Run with --export-cookies first, or set OE_COOKIES_JSON.", file=sys.stderr)
        print("  Skipping guideline refresh.", file=sys.stderr)
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium", file=sys.stderr)
        return False

    GUIDELINES_DIR.mkdir(parents=True, exist_ok=True)
    targets = {t: q for t, q in TOPIC_QUESTIONS.items() if not topics or t in topics}
    success_count = 0

    for topic, question in targets.items():
        print(f"[OE] Querying: {topic}...")
        try:
            result = _query_oe_playwright(question, cookies)

            if not result["answer"] or len(result["answer"]) < 50:
                print(f"  [WARN] Answer too short, might need re-login", file=sys.stderr)
                continue

            cache = {
                "topic": topic,
                "question": question,
                "answer": result["answer"],
                "citations": result["citations"],
                "date": date.today().isoformat(),
            }
            cache_file = GUIDELINES_DIR / f"{topic}.json"
            with open(cache_file, "w") as f:
                json.dump(cache, f, indent=2, ensure_ascii=False)
            print(f"  Saved: {cache_file.name} ({len(result['answer'])} chars)")
            success_count += 1
        except Exception as e:
            print(f"  [ERROR] {topic}: {e}", file=sys.stderr)

        time.sleep(3)  # Be polite to OE

    print(f"\n[OE] Refreshed {success_count}/{len(targets)} topics.")
    return success_count > 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh OpenEvidence guideline cache")
    parser.add_argument("--topic", help="Single topic to refresh")
    parser.add_argument("--export-cookies", action="store_true", help="Interactive login to export cookies")
    args = parser.parse_args()

    if args.export_cookies:
        export_cookies()
    else:
        topics = [args.topic] if args.topic else None
        refresh(topics)
