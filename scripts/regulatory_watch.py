"""Watch Taiwan coverage and approval sources for the drugs on treatment cards (G5 #116, ADR-0022).

python scripts/regulatory_watch.py --database-url URL [--dry-run]

The cards are the last confirmed state, so nothing else is stored:
- NHI: each card's coverage source names the rule chapter and version it was checked against
  (DurgFileName=9.27._20260501.pdf). The NHI drug list (E41001) links each chapter's current PDF; a newer version, or
  a chapter no longer listed, is a finding.
- TFDA: each card's tfdaNote names its licences. A licence changed after the card's checkedAt, revoked, or gone from
  the open data is a finding, reported with the licence's current indication.

Each finding becomes one review issue, never a card edit: a person compares the texts and updates the card. Titles
carry the chapter and version or the licence and change date, and an issue with the same title in any state is never
opened again. A source that cannot be fetched is skipped for this run (the other still runs) and the job exits 1, so
the Cloud Run job-failure alert says so. Needs GH_TOKEN and GITHUB_REPOSITORY to open issues.
"""

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

NHI_LIST = "https://info.nhi.gov.tw/api/iode0000s01/Dataset?rId=A21030000I-E41001-001"
TFDA_LICENCES = "https://data.fda.gov.tw/data/opendata/export/37/json"
TITLE = "[G5 監測]"
RULE = re.compile(r"DurgFileName=(?P<chapter>\d+(?:\.\d+)*\.)_(?P<version>\d{8})\.pdf")
# "衛部藥輸字第029167號、第028291號": later numbers share the first one's prefix.
LICENCE = re.compile(r"(?P<prefix>衛[署部](?:藥|菌疫)[輸製]字)(?P<numbers>第\d{6}號(?:、第\d{6}號)*)")
ATTEMPTS = 3
TIMEOUT = 300  # seconds; the NHI list is about 97 MB

type Card = tuple[str, dict[str, Any]]  # (topic key, regulatory row)


class SourceUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    title: str
    body: str


@dataclass(frozen=True)
class Licence:
    changed: str  # YYYY-MM-DD, the latest change of any record under this number
    revoked: bool
    name: str
    indication: str


class Issues(Protocol):
    def existing_titles(self) -> set[str]: ...
    def create(self, finding: Finding) -> None: ...


# --- sources -------------------------------------------------------------------------------------------------------


def fetch(url: str) -> bytes:
    for attempt in range(ATTEMPTS):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                return response.read()
        except OSError as error:
            if attempt == ATTEMPTS - 1:
                raise SourceUnavailableError(f"{url}: {error}") from error
            time.sleep(30 * (attempt + 1))
    raise AssertionError("unreachable")


def rule_versions(nhi_csv: bytes) -> dict[str, tuple[str, str]]:
    """Chapter -> (newest version, its PDF link) across the NHI drug list."""
    newest: dict[str, tuple[str, str]] = {}
    for item in csv.DictReader(io.StringIO(nhi_csv.decode("utf-8-sig"))):
        match = RULE.search(item.get("給付規定章節連結") or "")
        if match and match["version"] > newest.get(match["chapter"], ("", ""))[0]:
            newest[match["chapter"]] = (match["version"], item["給付規定章節連結"])
    return newest


def licences(tfda_export: bytes) -> dict[str, Licence]:
    """Licence number -> latest state. The export is a zip holding one JSON file (or, in tests, the JSON itself)."""
    if tfda_export[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(tfda_export)) as archive:
            tfda_export = archive.read(archive.namelist()[0])
    found: dict[str, Licence] = {}
    for record in json.loads(tfda_export.decode("utf-8-sig")):
        number = record.get("許可證字號") or ""
        changed = (record.get("異動日期") or "").replace("/", "-")
        if number and changed >= found.get(number, Licence("", False, "", "")).changed:
            found[number] = Licence(
                changed, bool(record.get("註銷狀態")), record.get("英文品名") or "", record.get("適應症") or ""
            )
    return found


# --- findings ------------------------------------------------------------------------------------------------------


def licence_numbers(note: str) -> list[str]:
    return [m["prefix"] + n for m in LICENCE.finditer(note) for n in re.findall(r"第\d{6}號", m["numbers"])]


def _cards_list(cards: Iterable[Card]) -> str:
    return "\n".join(f"- {topic}：{row['regimen']}（卡片查核日 {row['checkedAt']}）" for topic, row in cards)


def nhi_findings(cards: list[Card], versions: dict[str, tuple[str, str]]) -> list[Finding]:
    by_chapter: dict[tuple[str, str], list[Card]] = defaultdict(list)
    for card in cards:
        for source in card[1].get("sources", []):
            if match := RULE.search(source):
                by_chapter[(match["chapter"], match["version"])].append(card)
    findings = []
    for (chapter, checked), affected in sorted(by_chapter.items()):
        if chapter not in versions:
            findings.append(
                Finding(
                    f"{TITLE} 健保給付規定 {chapter} 不在健保用藥品項中",
                    f"健保用藥品項（E41001）已沒有任何品項連到給付規定 {chapter}。卡片依據的是 {checked} 版。\n\n"
                    f"受影響的卡片：\n{_cards_list(affected)}\n\n請確認這個章節是否刪除或改號，更新卡片後關閉。",
                )
            )
        elif (current := versions[chapter])[0] > checked:
            findings.append(
                Finding(
                    f"{TITLE} 健保給付規定 {chapter} 有新版 {current[0]}",
                    f"卡片依據 {checked} 版，健保用藥品項現在連到 {current[0]} 版：\n{current[1]}\n\n"
                    f"受影響的卡片：\n{_cards_list(affected)}\n\n請對照新舊條文，更新卡片的 nhiNote、來源連結與查核日後關閉。"
                    "卡片不會自動修改。",
                )
            )
    return findings


def tfda_findings(cards: list[Card], found: dict[str, Licence]) -> list[Finding]:
    by_licence: dict[str, list[Card]] = defaultdict(list)
    for card in cards:
        for number in licence_numbers(card[1].get("tfdaNote", "")):
            by_licence[number].append(card)
    findings = []
    for number, affected in sorted(by_licence.items()):
        licence = found.get(number)
        if licence is None or licence.revoked:
            findings.append(
                Finding(
                    f"{TITLE} TFDA 許可證 {number} 已註銷或不在清單中",
                    f"TFDA 未註銷藥品許可證開放資料中，{number} 已標示註銷或查無資料。\n\n"
                    f"受影響的卡片：\n{_cards_list(affected)}\n\n請確認後更新卡片的 tfda 欄位與 tfdaNote。",
                )
            )
            continue
        stale = [card for card in affected if licence.changed > card[1]["checkedAt"]]
        if stale:
            findings.append(
                Finding(
                    f"{TITLE} TFDA 許可證 {number} 於 {licence.changed} 異動",
                    f"{licence.name}（{number}）的許可證資料在 {licence.changed} 異動，晚於下列卡片的查核日。"
                    "異動不一定是適應症，請對照下方目前的適應症全文：\n\n"
                    f"> {licence.indication.replace(chr(10), chr(10) + '> ')}\n\n"
                    f"受影響的卡片：\n{_cards_list(stale)}\n\n確認後更新卡片的 tfdaNote 與查核日再關閉。",
                )
            )
    return findings


# --- run -----------------------------------------------------------------------------------------------------------


def run(cards: list[Card], get: Callable[[str], bytes], issues: Issues) -> int:
    findings: list[Finding] = []
    failed: list[str] = []
    for url, check in (
        (NHI_LIST, lambda data: nhi_findings(cards, rule_versions(data))),
        (TFDA_LICENCES, lambda data: tfda_findings(cards, licences(data))),
    ):
        try:
            findings += check(get(url))
        except SourceUnavailableError as error:
            print(f"source unavailable: {error}", file=sys.stderr)
            failed.append(url)
    existing = issues.existing_titles()
    new = [finding for finding in findings if finding.title not in existing]
    for finding in new:
        issues.create(finding)
    print(
        json.dumps({"job": "regulatory-watch", "findings": len(findings), "opened": len(new), "failedSources": failed})
    )
    return 1 if failed else 0


class GitHubIssues:
    """Issues through the gh CLI, as the other Paper Watch jobs do."""

    def __init__(self, repo: str, dry_run: bool) -> None:
        self.repo, self.dry_run = repo, dry_run

    def _gh(self, *args: str) -> str:
        return subprocess.run(["gh", *args, "--repo", self.repo], check=True, capture_output=True, text=True).stdout

    def existing_titles(self) -> set[str]:
        out = self._gh("issue", "list", "--state", "all", "--search", f'"{TITLE}" in:title', "--limit", "500",
                       "--json", "title")  # fmt: skip
        return {item["title"] for item in json.loads(out)}

    def create(self, finding: Finding) -> None:
        if self.dry_run:
            print(f"[dry run] {finding.title}")
            return
        self._gh("issue", "create", "--title", finding.title, "--body", finding.body)


def load_cards(url: str) -> list[Card]:
    import psycopg

    with psycopg.connect(url) as conn:
        rows = conn.execute(
            "select t.key, r from app.topics t, jsonb_array_elements(t.standard_of_care) c,"
            " jsonb_array_elements(coalesce(c->'regulatory', '[]')) r order by t.key"
        ).fetchall()
    return [(key, row) for key, row in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=os.environ.get("GUTHUB_CONTENT_DATABASE_URL"))
    parser.add_argument("--dry-run", action="store_true", help="list findings without opening issues")
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("--database-url or GUTHUB_CONTENT_DATABASE_URL is required")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        parser.error("GITHUB_REPOSITORY is required")
    return run(load_cards(args.database_url), fetch, GitHubIssues(repo, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
