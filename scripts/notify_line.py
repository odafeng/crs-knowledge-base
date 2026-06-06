"""LINE push notification for high-relevance papers (score >= 4)."""

import json
import sys
import urllib.request

from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
MAX_LENGTH = 5000


def _format_paper_message(paper):
    """Format a single paper into a LINE-friendly text block."""
    score = paper.get("ai_score", "?")
    topic = paper.get("topic", "")
    title = paper.get("title", "Untitled")
    journal = paper.get("journal", "")
    year = paper.get("year", "")
    doi = paper.get("doi", "")
    bottom_line = paper.get("ai_bottom_line", "")
    action = "Auto-PR" if score and score >= 5 else "GitHub Issue"

    lines = []
    if score and score >= 5:
        lines.append(f"🔥 Practice-Changing (Score {score}/5)")
    else:
        lines.append(f"📄 High-Impact (Score {score}/5)")

    lines.append(f"📌 {topic}")
    lines.append(f"")
    lines.append(title)
    lines.append(f"{journal} {year}")

    if bottom_line:
        lines.append(f"")
        lines.append(f"💡 {bottom_line}")

    if doi:
        lines.append(f"")
        lines.append(f"🔗 https://doi.org/{doi}")

    lines.append(f"")
    lines.append(f"→ {action} created on GitHub")

    return "\n".join(lines)


def format_digest(papers):
    """Format all papers into a single LINE digest message."""
    if not papers:
        return ""

    score_5 = [p for p in papers if p.get("ai_score") and p["ai_score"] >= 5]
    score_4 = [p for p in papers if p not in score_5]

    lines = [
        "📚 CRS Knowledge Base — Paper Watch",
        f"Found {len(papers)} relevant paper(s)",
        f"🔥 Practice-changing: {len(score_5)} | 📄 High-impact: {len(score_4)}",
        "─" * 20,
    ]

    for paper in score_5 + score_4:
        lines.append("")
        lines.append(_format_paper_message(paper))
        lines.append("─" * 20)

    msg = "\n".join(lines)
    if len(msg) > MAX_LENGTH:
        msg = msg[:MAX_LENGTH - 3] + "..."
    return msg


def send_line(message):
    """Push a text message to the configured LINE user. Returns True on success."""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] No LINE credentials configured. Skipping notification.", file=sys.stderr)
        return False

    payload = json.dumps({
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        LINE_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print("[LINE] Notification sent successfully.")
                return True
            print(f"[LINE] Unexpected status: {resp.status}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[LINE] Failed to send: {e}", file=sys.stderr)
        return False


def notify_papers(papers, dry_run=False):
    """Send LINE notification for high-relevance papers."""
    if not papers:
        return

    message = format_digest(papers)
    if not message:
        return

    if dry_run:
        print(f"\n[LINE DRY RUN]\n{message}")
        return

    send_line(message)
