"""Monthly review of KB content that may be out of date (#48).

Lists papers, treatment cards and regulatory rows whose last check is older
than the thresholds in config.py, and treatment cards that cite a trial a newer
KB entry supersedes. The list is kept in one tracking issue, edited in place;
nothing in the KB is changed automatically.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date

from config import PAPERS_JSON, STALE_PAPER_DAYS, STALE_REGULATORY_DAYS, STALE_SOC_DAYS
from gh_cli import ensure_labels, run_gh

ISSUE_TITLE = "[Stale] 內容複查清單"
LABEL = "stale-review"


@dataclass
class StaleItem:
    topic: str
    what: str
    checked: str
    reason: str


def _age(day: str, today: date) -> int:
    return (today - date.fromisoformat(day)).days


def find_stale(data: dict, today: date) -> list[StaleItem]:
    items = []
    for topic, topic_data in data.items():
        papers = topic_data.get("papers", [])
        superseded_by = {r["targetId"]: p for p in papers for r in p.get("relations", []) if r["type"] == "supersedes"}

        for p in papers:
            if p.get("reviewedAt") and _age(p["reviewedAt"], today) > STALE_PAPER_DAYS:
                items.append(
                    StaleItem(topic, f"試驗卡片 `{p['id']}`", p["reviewedAt"], f"超過 {STALE_PAPER_DAYS} 天未審核")
                )

        for card in topic_data.get("standard_of_care", {}).get("cards", []):
            name = f"治療方案「{card['title']}」"
            if _age(card["reviewedAt"], today) > STALE_SOC_DAYS:
                items.append(StaleItem(topic, name, card["reviewedAt"], f"超過 {STALE_SOC_DAYS} 天未審核"))
            for ref in card.get("refs", []):
                newer = superseded_by.get(ref)
                if newer and newer.get("reviewedAt", "") > card["reviewedAt"]:
                    items.append(
                        StaleItem(
                            topic,
                            name,
                            card["reviewedAt"],
                            f"引用的 `{ref}` 已有更新報告 `{newer['id']}`（{newer['reviewedAt']} 收錄）",
                        )
                    )
            for row in card.get("regulatory", []):
                if _age(row["checkedAt"], today) > STALE_REGULATORY_DAYS:
                    items.append(
                        StaleItem(
                            topic,
                            f"{name} 的核准 / 給付：{row['regimen']}",
                            row["checkedAt"],
                            f"超過 {STALE_REGULATORY_DAYS} 天未確認",
                        )
                    )
    return items


def format_report(items: list[StaleItem], today: date) -> str:
    lines = [
        f"每月自動檢查，最後執行：{today.isoformat()}。本 issue 會被下一次檢查覆寫；處理完的項目更新 `reviewedAt` / `checkedAt` 即可。",
        "",
    ]
    if not items:
        return "\n".join([*lines, "目前沒有過期內容。"])
    lines += ["| Topic | 項目 | 上次審核 | 原因 |", "|---|---|---|---|"]
    lines += [f"| {i.topic} | {i.what} | {i.checked} | {i.reason} |" for i in items]
    return "\n".join(lines)


def sync_issue(body: str, has_items: bool) -> None:
    """Edit the open tracking issue in place, open one if needed, close it when the list is empty."""
    ok, out = run_gh(["issue", "list", "--label", LABEL, "--state", "open", "--json", "number", "--jq", ".[0].number"])
    number = out.strip() if ok else ""
    if number:
        run_gh(["issue", "edit", number, "--body", body])
        if not has_items:
            run_gh(["issue", "close", number, "--reason", "completed", "--comment", "目前沒有過期內容。"])
        print(f"[Stale] Updated issue #{number}")
    elif has_items:
        ensure_labels({LABEL})
        run_gh(["issue", "create", "--title", ISSUE_TITLE, "--label", LABEL, "--body", body])
        print("[Stale] Opened tracking issue")


def main() -> int:
    parser = argparse.ArgumentParser(description="List KB content due for review")
    parser.add_argument("--dry-run", action="store_true", help="print the report, don't touch issues")
    args = parser.parse_args()
    today = date.today()
    items = find_stale(json.loads(PAPERS_JSON.read_text()), today)
    body = format_report(items, today)
    print(body)
    if not args.dry_run:
        sync_issue(body, bool(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
