"""Tests for backend pending-deploy detection and tracking issue sync (K8 #258)."""

from pathlib import Path
from unittest.mock import patch

import deploy_status


def _state(
    *,
    pending: tuple[deploy_status.CommitInfo, ...] = (),
    risky: tuple[deploy_status.CommitInfo, ...] = (),
    staging_ready: bool = True,
    last_prod: str | None = "1111111abcdef",
    last_staging: str | None = "2222222abcdef",
) -> deploy_status.DeployState:
    return deploy_status.DeployState(
        head_sha="3333333abcdef",
        last_prod_sha=last_prod,
        last_staging_sha=last_staging,
        pending_commits=pending,
        risky_commits=risky,
        staging_ready=staging_ready,
    )


def test_format_markdown_reports_synced_state() -> None:
    text = deploy_status.format_markdown(_state(), "owner/repo")
    assert "已與 `main` 同步" in text
    assert "`3333333`" in text


def test_format_markdown_distinguishes_ready_vs_staging_needed() -> None:
    c1 = deploy_status.CommitInfo("aaaaaaa111", "feat(api): add by-slug endpoint")
    c2 = deploy_status.CommitInfo("bbbbbbb222", "feat(db): add pg_trgm search index")

    non_risky = deploy_status.format_markdown(_state(pending=(c1,)), "owner/repo")
    assert "無 schema／auth／部署設定異動" in non_risky
    assert "`aaaaaaa` feat(api): add by-slug endpoint" in non_risky

    waiting_staging = deploy_status.format_markdown(
        _state(pending=(c2, c1), risky=(c2,), staging_ready=False),
        "owner/repo",
    )
    assert "請先確認 [Deploy staging]" in waiting_staging
    assert "需先經 Staging 演練的變更" in waiting_staging

    staging_done = deploy_status.format_markdown(
        _state(pending=(c2, c1), risky=(c2,), staging_ready=True),
        "owner/repo",
    )
    assert "Staging 演練狀態**：✅ 已通過" in staging_done


def test_sync_tracking_issue_creates_updates_and_closes() -> None:
    pending_state = _state(pending=(deploy_status.CommitInfo("aaaaaaa111", "feat(api): x"),))

    with (
        patch.object(deploy_status, "_find_open_tracking_issue", return_value=None),
        patch.object(deploy_status, "_run", return_value="https://github.com/owner/repo/issues/999") as run_mock,
    ):
        assert (
            deploy_status.sync_tracking_issue(pending_state, "owner/repo")
            == "created https://github.com/owner/repo/issues/999"
        )
        assert run_mock.call_args.args[0][:3] == ["gh", "issue", "create"]

    with (
        patch.object(deploy_status, "_find_open_tracking_issue", return_value={"number": 999}),
        patch.object(deploy_status, "_run", return_value="") as run_mock,
    ):
        assert deploy_status.sync_tracking_issue(pending_state, "owner/repo") == "updated #999"
        assert run_mock.call_args.args[0][:4] == ["gh", "issue", "edit", "999"]

    synced_state = _state()
    with (
        patch.object(deploy_status, "_find_open_tracking_issue", return_value={"number": 999}),
        patch.object(deploy_status, "_run", return_value="") as run_mock,
    ):
        assert deploy_status.sync_tracking_issue(synced_state, "owner/repo") == "closed #999"
        assert run_mock.call_count == 2
        assert run_mock.call_args_list[0].args[0][:4] == ["gh", "issue", "comment", "999"]
        assert run_mock.call_args_list[1].args[0][:4] == ["gh", "issue", "close", "999"]


def test_risky_paths_stay_in_sync_with_deploy_staging_workflow() -> None:
    staging_yml = (Path(__file__).resolve().parent.parent / ".github/workflows/deploy-staging.yml").read_text(
        encoding="utf-8"
    )
    for path in deploy_status.RISKY_PATHS:
        assert path in staging_yml, f"{path} missing from deploy-staging.yml"


def test_find_open_tracking_issue_uses_rest_api_and_ignores_prs_and_non_bots() -> None:
    payload = [
        [
            {
                "number": 1,
                "title": deploy_status.ISSUE_TITLE,
                "user": {"login": "github-actions[bot]"},
                "pull_request": {},
            },
            {"number": 2, "title": deploy_status.ISSUE_TITLE, "user": {"login": "random-user"}},
            {"number": 3, "title": deploy_status.ISSUE_TITLE, "user": {"login": "github-actions[bot]"}},
        ]
    ]
    import json

    with patch.object(deploy_status, "_run", return_value=json.dumps(payload)):
        found = deploy_status._find_open_tracking_issue("owner/repo")
    assert found is not None
    assert found["number"] == 3
