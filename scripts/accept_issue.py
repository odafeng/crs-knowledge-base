"""Publish a held paper or commentary after a reviewer adds the `accepted` label (ADR-0013).

The workflow passes the issue body in a file; this script only edits the KB files.
Committing, pushing and commenting on the issue happen in the workflow.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from issue_data import checked_indices, extract
from publish import KB, PublishError, publish_commentary, publish_paper


def accept(body: str, today: str, kb: KB | None = None) -> str:
    """Apply the issue's payload to the KB. Returns a one-line summary for the commit and comment."""
    paper = extract(body, "paper")
    if paper:
        entry = publish_paper(paper, "accepted", today, kb)
        return f"publish {entry['id']} ({entry['file']})"

    proposals = extract(body, "commentary")
    if proposals:
        picked = checked_indices(body)
        items = [(p["target_id"], p["entry"]) for p in proposals if p["index"] in picked]
        if not items:
            raise PublishError(["沒有勾選任何評論；勾選要收錄的項目後，移除再重新加上 `accepted` label"])
        changed = publish_commentary(items, "accepted", today, kb)
        return f"publish commentary on {', '.join(changed) or 'nothing new'}"

    raise PublishError(["這個 issue 沒有可發布的資料（可能是改版前開的 issue），請手動整理"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an accepted review issue")
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--result-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = accept(args.body_file.read_text(), date.today().isoformat())
    except PublishError as e:
        args.result_file.write_text("無法發布：\n" + "\n".join(f"- {r}" for r in e.reasons))
        print(e, file=sys.stderr)
        return 1
    args.result_file.write_text(summary)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
