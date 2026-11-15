"""Tests for the monthly stale-content review."""

from datetime import date
from unittest.mock import patch

from check_stale import find_stale, format_report, sync_issue

TODAY = date(2027, 6, 1)


def _data(paper_reviewed="2027-05-01", card_reviewed="2027-05-01", checked="2027-05-01", newer_reviewed=None):
    papers = [{"id": "old-trial", "reviewedAt": paper_reviewed, "relations": []}]
    if newer_reviewed:
        papers.append(
            {
                "id": "old-trial-os",
                "reviewedAt": newer_reviewed,
                "relations": [{"targetId": "old-trial", "type": "supersedes"}],
            }
        )
    card = {
        "title": "一線治療",
        "reviewedAt": card_reviewed,
        "refs": ["old-trial"],
        "regulatory": [{"regimen": "Drug A", "checkedAt": checked}],
    }
    return {"t": {"papers": papers, "standard_of_care": {"title": "x", "cards": [card]}}}


def test_fresh_content_is_not_listed():
    assert find_stale(_data(), TODAY) == []


def test_old_paper_card_and_regulatory_rows():
    items = find_stale(_data(paper_reviewed="2026-01-01", card_reviewed="2026-11-01", checked="2026-11-01"), TODAY)
    reasons = [(i.what, i.reason) for i in items]
    assert ("試驗卡片 `old-trial`", "超過 365 天未審核") in reasons
    assert any(what == "治療方案「一線治療」" and "182" in reason for what, reason in reasons)
    assert any("核准 / 給付：Drug A" in what for what, _ in reasons)


def test_card_citing_superseded_trial():
    items = find_stale(_data(newer_reviewed="2027-05-20"), TODAY)
    assert len(items) == 1
    assert "已有更新報告 `old-trial-os`" in items[0].reason


def test_update_reviewed_before_card_is_not_listed():
    assert find_stale(_data(card_reviewed="2027-05-25", newer_reviewed="2027-05-20"), TODAY) == []


def test_report_and_issue_sync():
    items = find_stale(_data(paper_reviewed="2026-01-01"), TODAY)
    body = format_report(items, TODAY)
    assert "| t | 試驗卡片 `old-trial` | 2026-01-01 |" in body

    with patch("check_stale.run_gh", return_value=(True, "")) as gh, patch("check_stale.ensure_labels"):
        sync_issue(body, has_items=True)
    assert gh.call_args.args[0][:2] == ["issue", "create"]

    with patch("check_stale.run_gh", return_value=(True, "48\n")) as gh:
        sync_issue(body, has_items=True)
    assert [c.args[0][:2] for c in gh.call_args_list] == [["issue", "list"], ["issue", "edit"]]

    with patch("check_stale.run_gh", return_value=(True, "48\n")) as gh:
        sync_issue(format_report([], TODAY), has_items=False)
    assert gh.call_args.args[0][:2] == ["issue", "close"]
