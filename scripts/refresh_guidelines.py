"""Refresh guideline cache by querying OpenEvidence via relay daemon.

This script is meant to be run locally (or via Claude Code scheduled trigger)
when the OpenEvidence relay is available. It queries guidelines for all 6 topics
and saves responses to data/guidelines/.

Usage:
  python scripts/refresh_guidelines.py              # refresh all topics
  python scripts/refresh_guidelines.py --topic mCRC-BRAF-V600E  # single topic
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

GUIDELINES_DIR = Path(__file__).resolve().parent.parent / "data" / "guidelines"
OE_RELAY_URL = "http://127.0.0.1:8787"

TOPIC_QUESTIONS = {
    "mCRC-BRAF-V600E": "What are the current ASCO and NCCN guideline recommendations for treatment of BRAF V600E mutant metastatic colorectal cancer? Include first-line and second-line recommendations, and note any recent updates from BREAKWATER trial data.",
    "mCRC-KRAS-G12C": "What are the current ASCO and NCCN guideline recommendations for KRAS G12C mutant metastatic colorectal cancer? Include approved agents (sotorasib, adagrasib) and recommended combinations with anti-EGFR.",
    "mCRC-MSI-H": "What are the current ASCO and NCCN guideline recommendations for MSI-H/dMMR colorectal cancer? Cover both metastatic (first-line immunotherapy) and localized settings (neoadjuvant immunotherapy, non-operative management for rectal cancer).",
    "mCRC-HER2": "What are the current NCCN guideline recommendations for HER2-amplified metastatic colorectal cancer? Include approved regimens (tucatinib+trastuzumab, trastuzumab deruxtecan) and testing recommendations.",
    "mCRC-RAS-wt": "What are the current ASCO and NCCN guideline recommendations for RAS wild-type metastatic colorectal cancer regarding anti-EGFR therapy? Cover first-line selection (cetuximab vs bevacizumab), tumor sidedness, maintenance therapy, and rechallenge strategies.",
    "robotic-surgery": "What are the current guidelines and consensus statements regarding robotic surgery for rectal cancer (robotic TME)? Include evidence from REAL trial and recommendations from ESCP, ASCRS, or other surgical societies.",
}


def _relay_available():
    try:
        req = urllib.request.Request(f"{OE_RELAY_URL}/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            return data.get("ok", False) and data.get("connected", False)
    except Exception:
        return False


def _query_oe(question):
    """Submit question to OE relay and poll for answer."""
    payload = json.dumps({
        "question": question,
        "article_type": "Ask OpenEvidence Light with citations",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OE_RELAY_URL}/api/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())

    article_id = result.get("article_id") or result.get("id")
    if not article_id:
        answer = result.get("extracted_answer_raw") or result.get("content")
        if answer:
            return {"answer": answer, "citations": []}
        raise ValueError(f"No article_id: {result}")

    # Poll
    for _ in range(90):
        time.sleep(2)
        poll_req = urllib.request.Request(f"{OE_RELAY_URL}/api/article/{article_id}")
        with urllib.request.urlopen(poll_req, timeout=15) as resp:
            article = json.loads(resp.read())

        status = article.get("status", "")
        if status in ("success", "completed", "done"):
            return {
                "answer": article.get("extracted_answer_raw") or article.get("content") or "",
                "citations": article.get("citations") or [],
            }
        if status in ("failed", "error"):
            raise ValueError(f"OE query failed: {article.get('error')}")

    raise TimeoutError("OE query timed out")


def refresh(topics=None):
    if not _relay_available():
        print("[ERROR] OpenEvidence relay not running (127.0.0.1:8787).", file=sys.stderr)
        print("  Start it: cd openevidence-mcp && make all", file=sys.stderr)
        return False

    GUIDELINES_DIR.mkdir(parents=True, exist_ok=True)
    targets = {t: q for t, q in TOPIC_QUESTIONS.items() if not topics or t in topics}

    for topic, question in targets.items():
        print(f"[OE] Querying: {topic}...")
        try:
            result = _query_oe(question)
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
        except Exception as e:
            print(f"  [ERROR] {topic}: {e}", file=sys.stderr)

        time.sleep(1)

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", help="Single topic to refresh")
    args = parser.parse_args()
    topics = [args.topic] if args.topic else None
    refresh(topics)
