"""LINE push notification for high-relevance papers (score >= 4)."""

import json
import sys
import urllib.request

from config import LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
MAX_LENGTH = 5000

TOPIC_LABELS = {
    "mCRC-BRAF-V600E": "BRAF V600E",
    "mCRC-KRAS-G12C": "KRAS G12C",
    "mCRC-MSI-H": "MSI-H / dMMR",
    "mCRC-HER2": "HER2+",
    "mCRC-RAS-wt": "RAS 野生型",
    "generic-CRS": "大腸直腸癌通用",
    "robotic-surgery": "機器人手術",
}


def _format_paper_message(paper):
    """Format a single paper into a plain Traditional Chinese LINE summary block (K13 #265)."""
    score = paper.get("ai_score", "?")
    topic_key = paper.get("topic", "")
    topic = TOPIC_LABELS.get(topic_key, topic_key)
    title = paper.get("title", "Untitled")
    journal = paper.get("journal", "")
    year = paper.get("year", "")
    doi = paper.get("doi", "")
    bottom_line = paper.get("ai_bottom_line", "")
    action = "已自動發布上站（待審）" if paper.get("publish_status") == "auto" else "待人工審核，已開 GitHub Issue"

    lines = []
    if isinstance(score, int) and score >= 5:
        lines.append(f"🔥 重大臨床進展（{score}/5）｜{topic}")
    else:
        lines.append(f"📄 重要新文獻（{score}/5）｜{topic}")

    lines.append(title)
    if journal or year:
        lines.append(f"出處：{' '.join(str(x) for x in (journal, year) if x)}")

    if bottom_line:
        lines.append(f"重點：{bottom_line}")

    if doi:
        lines.append(f"連結：https://doi.org/{doi}")

    lines.append(f"狀態：{action}")

    return "\n".join(lines)


def format_digest(papers):
    """Format all high-relevance papers into a single maintainer LINE digest message."""
    if not papers:
        return ""

    score_5 = [p for p in papers if isinstance(p.get("ai_score"), int) and p["ai_score"] >= 5]
    score_4 = [p for p in papers if p not in score_5]

    lines = [
        "GutHub｜Paper Watch 掃描通知",
        f"本次篩出 {len(papers)} 篇高相關文獻（重大進展 {len(score_5)}｜重要文獻 {len(score_4)}）",
        "─" * 20,
    ]

    for paper in score_5 + score_4:
        lines.append("")
        lines.append(_format_paper_message(paper))
        lines.append("─" * 20)

    msg = "\n".join(lines)
    if len(msg) > MAX_LENGTH:
        msg = msg[: MAX_LENGTH - 3] + "..."
    return msg


def send_line(message):
    """Push a text message to the configured LINE user. Returns True on success."""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("[LINE] No LINE credentials configured. Skipping notification.", file=sys.stderr)
        return False

    payload = json.dumps(
        {
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": message}],
        }
    ).encode("utf-8")

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
