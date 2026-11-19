from unittest.mock import MagicMock, patch

import gh_cli


def test_gh_is_told_the_repo_so_it_needs_no_git_checkout():
    done = MagicMock(returncode=0, stdout="https://example.test/issues/1\n")
    with (
        patch.object(gh_cli, "GITHUB_TOKEN", "t"),
        patch.object(gh_cli, "GITHUB_REPO", "owner/repo"),
        patch("gh_cli.subprocess.run", return_value=done) as run,
    ):
        assert gh_cli.run_gh(["issue", "create"]) == (True, "https://example.test/issues/1")
    assert run.call_args.kwargs["env"]["GH_REPO"] == "owner/repo"


def test_no_repo_set_leaves_gh_to_find_it():
    done = MagicMock(returncode=0, stdout="")
    with (
        patch.object(gh_cli, "GITHUB_TOKEN", "t"),
        patch.object(gh_cli, "GITHUB_REPO", ""),
        patch("gh_cli.subprocess.run", return_value=done) as run,
    ):
        gh_cli.run_gh(["label", "list"])
    assert "GH_REPO" not in run.call_args.kwargs["env"]
