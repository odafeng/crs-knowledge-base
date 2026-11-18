"""Open the forum's first threads as GutHub AI (H9 #161, ADR-0022).

python scripts/forum_ai_topics.py --database-url URL [--dry-run]

Posts each draft in data/forum_ai_topics.json that the maintainer marked "approved": true and that is not posted yet
(an AI thread with the same title). Drafts are written only from the site's own evidence, copy its numbers, and name
their sources; they ask questions rather than give clinical advice. An AI post belongs to no account, is signed
"GutHub AI" and is labelled AI on the site; the database publishes it at once because its draft was reviewed. Runs as
the content owner: the API cannot insert AI posts. Prints what it posted and when, for the record in #161.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DRAFTS = Path(__file__).resolve().parents[1] / "data" / "forum_ai_topics.json"
DISPLAY_NAME = "GutHub AI"
TITLE_MAX = 120
BODY_MAX = 5000
FOOTER = "\n\n（這個話題由 GutHub AI 依站上已整理的實證開啟，數字照抄站上條目，不是臨床建議。歡迎直接回覆你的做法。）"


def load(path: Path = DRAFTS) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["drafts"]


def problems(draft: dict[str, Any]) -> list[str]:
    """What keeps a draft from being posted, checked before anything is written."""
    found = []
    if not 1 <= len(draft["title"].strip()) <= TITLE_MAX:
        found.append(f"{draft['key']}: title must be 1-{TITLE_MAX} characters")
    if not 1 <= len(draft["body"] + FOOTER) <= BODY_MAX:
        found.append(f"{draft['key']}: body must fit in {BODY_MAX} characters with the footer")
    if "來源" not in draft["body"]:
        found.append(f"{draft['key']}: body must name its sources on the site")
    return found


def post(conn: Any, drafts: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    approved = [d for d in drafts if d.get("approved") is True]
    errors = [p for d in approved for p in problems(d)]
    for d in approved:
        if (
            d.get("paperId")
            and not conn.execute("select 1 from app.public_papers where id = %s", (d["paperId"],)).fetchone()
        ):
            errors.append(f"{d['key']}: paper {d['paperId']} is not public")
        if (
            d.get("topicKey")
            and not conn.execute("select 1 from app.topics where key = %s", (d["topicKey"],)).fetchone()
        ):
            errors.append(f"{d['key']}: unknown topic {d['topicKey']}")
    if errors:
        raise ValueError("; ".join(errors))
    posted, skipped = [], []
    for d in approved:
        exists = conn.execute(
            "select 1 from app.forum_posts where ai and thread_id is null and title = %s and deleted_at is null",
            (d["title"].strip(),),
        ).fetchone()
        if exists:
            skipped.append(d["key"])
            continue
        if not dry_run:
            conn.execute(
                "insert into app.forum_posts (title, topic_key, paper_id, body, anonymous, display_name, ai)"
                " values (%s, %s, %s, %s, false, %s, true)",
                (d["title"].strip(), d.get("topicKey"), d.get("paperId"), d["body"] + FOOTER, DISPLAY_NAME),
            )
        posted.append(d["key"])
    return {
        "approved": len(approved),
        "posted": posted,
        "skipped": skipped,
        "pending": [d["key"] for d in drafts if d.get("approved") is not True],
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dryRun": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("GUTHUB_CONTENT_DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="check the approved drafts, write nothing")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url (or GUTHUB_CONTENT_DATABASE_URL) is required")
    import psycopg

    with psycopg.connect(args.database_url) as conn, conn.transaction():
        report = post(conn, load(), args.dry_run)
    print(json.dumps({"job": "forum-ai-topics", **report}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
