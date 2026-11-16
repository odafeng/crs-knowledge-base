"""Coverage and approval watch (G5 #116): findings from fixed samples, deduplication and unreachable sources."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import regulatory_watch as watch

FIXTURES = Path(__file__).parent / "fixtures" / "regulatory"
NHI = (FIXTURES / "nhi.csv").read_bytes()
TFDA = (FIXTURES / "tfda.json").read_bytes()
RULE = "https://info.nhi.gov.tw/api/INAE3000/INAE3000S01/getPDF?DurgFileName={}"


def row(regimen: str, rule: str, licence: str, checked: str = "2026-11-17") -> tuple[str, dict]:
    return (
        "mCRC-RAS-wt",
        {
            "regimen": regimen,
            "nhiNote": f"給付規定 {rule}",
            "tfdaNote": f"品名（{licence}）",
            "sources": ["https://data.fda.gov.tw/data/opendata/export/37/json", RULE.format(rule)],
            "checkedAt": checked,
        },
    )


CARDS = [
    row("Cetuximab + FOLFIRI", "9.27._20260501.pdf", "衛署菌疫輸字第000877號"),
    row("Panitumumab + FOLFOX", "9.53._20260201.pdf", "衛署菌疫輸字第000941號"),
]


def titles(findings: list[watch.Finding]) -> list[str]:
    return [f.title for f in findings]


def test_cards_that_match_the_sources_raise_nothing() -> None:
    assert watch.nhi_findings(CARDS, watch.rule_versions(NHI)) == []
    assert watch.tfda_findings(CARDS, watch.licences(TFDA)) == []


def test_a_new_rule_version_is_one_finding_per_chapter_listing_every_card() -> None:
    newer = NHI.replace(b"9.27._20260501", b"9.27._20261101")
    cards = [*CARDS, row("Encorafenib + cetuximab", "9.27._20260501.pdf", "衛署菌疫輸字第000877號")]
    [finding] = watch.nhi_findings(cards, watch.rule_versions(newer))
    assert finding.title == "[G5 監測] 健保給付規定 9.27. 有新版 20261101"
    assert "Cetuximab + FOLFIRI" in finding.body and "Encorafenib + cetuximab" in finding.body
    assert "DurgFileName=9.27._20261101.pdf" in finding.body and "20260501" in finding.body


def test_a_chapter_missing_from_the_list_is_reported() -> None:
    gone = NHI.replace(b"9.53.", b"9.99.")
    assert titles(watch.nhi_findings(CARDS, watch.rule_versions(gone))) == [
        "[G5 監測] 健保給付規定 9.53. 不在健保用藥品項中"
    ]


def test_a_licence_changed_after_the_card_was_checked_is_reported_with_its_indication() -> None:
    cards = [row("Panitumumab + FOLFOX", "9.53._20260201.pdf", "衛署菌疫輸字第000941號", checked="2026-02-01")]
    [finding] = watch.tfda_findings(cards, watch.licences(TFDA))
    assert finding.title == "[G5 監測] TFDA 許可證 衛署菌疫輸字第000941號 於 2026-03-01 異動"
    assert "RAS 基因正常轉移性大腸直腸癌" in finding.body


def test_a_revoked_or_missing_licence_is_reported() -> None:
    records = json.loads(TFDA)
    records[2]["註銷狀態"] = "已註銷"
    revoked = json.dumps(records, ensure_ascii=False).encode()
    found = titles(watch.tfda_findings(CARDS, watch.licences(revoked)))
    assert found == ["[G5 監測] TFDA 許可證 衛署菌疫輸字第000941號 已註銷或不在清單中"]


class FakeIssues:
    def __init__(self, existing: list[str]) -> None:
        self.titles = list(existing)
        self.created: list[str] = []

    def existing_titles(self) -> set[str]:
        return set(self.titles)

    def create(self, finding: watch.Finding) -> None:
        self.created.append(finding.title)
        self.titles.append(finding.title)


def fetcher(sources: dict[str, bytes | Exception]):
    def fetch(url: str) -> bytes:
        value = sources[url]
        if isinstance(value, Exception):
            raise value
        return value

    return fetch


def test_findings_open_one_issue_each_and_never_twice(capsys: pytest.CaptureFixture[str]) -> None:
    newer = NHI.replace(b"9.27._20260501", b"9.27._20261101")
    issues = FakeIssues(existing=[])
    fetch = fetcher({watch.NHI_LIST: newer, watch.TFDA_LICENCES: TFDA})
    assert watch.run(CARDS, fetch, issues) == 0
    assert issues.created == ["[G5 監測] 健保給付規定 9.27. 有新版 20261101"]
    # Next week, same sources: the issue exists (open or closed), so nothing new is opened.
    assert watch.run(CARDS, fetch, issues) == 0
    assert len(issues.created) == 1
    assert '"opened": 0' in capsys.readouterr().out.strip().splitlines()[-1]


def test_an_unreachable_source_opens_nothing_for_it_but_the_other_still_runs() -> None:
    issues = FakeIssues(existing=[])
    cards = [row("Panitumumab + FOLFOX", "9.53._20260201.pdf", "衛署菌疫輸字第000941號", checked="2026-02-01")]
    fetch = fetcher({watch.NHI_LIST: watch.SourceUnavailableError("timed out"), watch.TFDA_LICENCES: TFDA})
    # Exit status 1 so the job-failure alert fires; the TFDA finding is still opened.
    assert watch.run(cards, fetch, issues) == 1
    assert issues.created == ["[G5 監測] TFDA 許可證 衛署菌疫輸字第000941號 於 2026-03-01 異動"]


def test_the_tfda_export_is_read_from_its_zip(tmp_path: Path) -> None:
    import zipfile

    archive = tmp_path / "37.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("37_5.json", TFDA.decode())
    assert set(watch.licences(archive.read_bytes())) == {"衛署菌疫輸字第000877號", "衛署菌疫輸字第000941號"}


def test_licences_listed_after_a_shared_prefix_are_all_read() -> None:
    note = "Lumakras（衛部藥輸字第029167號、第028291號）與 Opdivo（衛部菌疫輸字第001013號）"
    assert watch.licence_numbers(note) == ["衛部藥輸字第029167號", "衛部藥輸字第028291號", "衛部菌疫輸字第001013號"]
