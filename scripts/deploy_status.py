"""Track backend/migration commits on main that have not yet been deployed to production (K8 #258).

python scripts/deploy_status.py --repo OWNER/REPO [--sync-issue]

Frontend changes deploy automatically via Vercel on every push to main, while production Cloud Run / Supabase
migrations require a manual Deploy production run (ADR-0024). This script compares main against the latest
successful `deploy-prod.yml` SHA and keeps a single tracking issue updated whenever backend/worker/migration
commits are pending, then closes it automatically once production catches up.
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ISSUE_TITLE = "[待部署] 正式環境後端有未上線變更"
BOT_LOGINS = {"github-actions[bot]", "app/github-actions"}

# Must match .github/workflows/deploy-prod.yml and deploy-staging.yml (ADR-0024).
RISKY_PATHS: tuple[str, ...] = (
    "supabase/migrations",
    "supabase/config.toml",
    "apps/api/src/guthub_api/auth.py",
    ".github/workflows/deploy.yml",
    ".github/workflows/deploy-staging.yml",
)

# Paths deployed by deploy.yml (Cloud Run API, worker jobs, Supabase).
BACKEND_PATHS: tuple[str, ...] = (
    "apps/api",
    "worker",
    "scripts",
    "newsroom",
    "supabase",
    "contracts/openapi.yaml",
    "import_content.py",
    "content_writer.py",
    ".github/workflows/deploy.yml",
    ".github/workflows/deploy-staging.yml",
)


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str


@dataclass(frozen=True)
class DeployState:
    head_sha: str
    last_prod_sha: str | None
    last_staging_sha: str | None
    pending_commits: tuple[CommitInfo, ...]
    risky_commits: tuple[CommitInfo, ...]
    staging_ready: bool


def _run(cmd: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(cmd, check=check, capture_output=True, text=True)
    return proc.stdout.strip()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], capture_output=True)
    return proc.returncode == 0


def _commits_touching(rev_range: str, paths: tuple[str, ...]) -> tuple[CommitInfo, ...]:
    out = _run(["git", "log", "--format=%H%x09%s", rev_range, "--", *paths])
    commits: list[CommitInfo] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, _, subject = line.partition("\t")
        commits.append(CommitInfo(sha=sha, subject=subject))
    return tuple(commits)


def _latest_workflow_sha(repo: str, workflow: str) -> str | None:
    out = _run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--workflow",
            workflow,
            "--branch",
            "main",
            "--status",
            "success",
            "--limit",
            "1",
            "--json",
            "headSha",
            "--jq",
            ".[0].headSha // empty",
        ]
    )
    return out or None


def collect_state(repo: str, head_sha: str | None = None) -> DeployState:
    head = head_sha or _run(["git", "rev-parse", "HEAD"])
    last_prod = _latest_workflow_sha(repo, "deploy-prod.yml")
    last_staging = _latest_workflow_sha(repo, "deploy-staging.yml")
    rev_range = f"{last_prod}..{head}" if last_prod else head
    pending = _commits_touching(rev_range, BACKEND_PATHS)
    risky = _commits_touching(rev_range, RISKY_PATHS)
    if not risky:
        staging_ready = True
    elif last_staging is not None:
        staging_ready = _is_ancestor(risky[0].sha, last_staging)
    else:
        staging_ready = False
    return DeployState(
        head_sha=head,
        last_prod_sha=last_prod,
        last_staging_sha=last_staging,
        pending_commits=pending,
        risky_commits=risky,
        staging_ready=staging_ready,
    )


def format_markdown(state: DeployState, repo: str) -> str:
    deploy_url = f"https://github.com/{repo}/actions/workflows/deploy-prod.yml"
    staging_url = f"https://github.com/{repo}/actions/workflows/deploy-staging.yml"
    prod_label = f"`{state.last_prod_sha[:7]}`" if state.last_prod_sha else "（尚無成功紀錄）"

    if not state.pending_commits:
        return (
            f"正式環境後端已與 `main` 同步（`{state.head_sha[:7]}`，上次正式部署：{prod_label}），"
            "目前沒有待部署的 API / Worker / Migration 變更。"
        )

    lines = [
        f"`main`（`{state.head_sha[:7]}`）目前有 **{len(state.pending_commits)}** 筆後端／資料庫變更尚未部署至正式環境"
        f"（上次 `Deploy production` 成功於 {prod_label}）。",
        "",
    ]

    if state.risky_commits:
        if state.staging_ready:
            staged_label = f"`{state.last_staging_sha[:7]}`" if state.last_staging_sha else ""
            lines.append(
                f"- **Staging 演練狀態**：✅ 已通過（staging 已包含最新風險變更 {staged_label}），"
                f"可直接前往 [Deploy production]({deploy_url}) 執行部署。"
            )
        else:
            lines.append(
                f"- **Staging 演練狀態**：⏳ 包含資料庫 migration／auth／部署流程變更，"
                f"請先確認 [Deploy staging]({staging_url}) 完成後再執行 [Deploy production]({deploy_url})。"
            )
        lines.append("")
        lines.append("### 需先經 Staging 演練的變更（ADR-0024）")
        for c in state.risky_commits[:20]:
            lines.append(f"- `{c.sha[:7]}` {c.subject}")
        lines.append("")
    else:
        lines.append(
            f"- **Staging 演練狀態**：✅ 無 schema／auth／部署設定異動，可直接前往 [Deploy production]({deploy_url}) 執行部署。"
        )
        lines.append("")

    lines.append("### 待部署的後端變更")
    for c in state.pending_commits[:30]:
        lines.append(f"- `{c.sha[:7]}` {c.subject}")
    if len(state.pending_commits) > 30:
        lines.append(f"- … 以及另外 {len(state.pending_commits) - 30} 筆")

    lines += [
        "",
        f"執行方式：開啟 [Deploy production]({deploy_url}) → Run workflow → 輸入 `production` 並核准部署。"
        "正式部署成功後本 issue 會自動關閉。",
    ]
    return "\n".join(lines)


def _find_open_tracking_issue(repo: str) -> dict | None:
    # Use the REST API rather than search so rapid pushes never miss an issue created seconds earlier.
    raw = _run(["gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues?state=open&per_page=100"])
    pages = json.loads(raw or "[]")
    for page in pages:
        for item in page:
            if "pull_request" in item:
                continue
            if item.get("title") == ISSUE_TITLE and item.get("user", {}).get("login") in BOT_LOGINS:
                return item
    return None


def sync_tracking_issue(state: DeployState, repo: str) -> str:
    """Create, update, or close the single pending-deploy tracking issue. Returns action taken."""
    existing = _find_open_tracking_issue(repo)
    body = format_markdown(state, repo)
    if not state.pending_commits:
        if existing is None:
            return "none"
        num = str(existing["number"])
        _run(["gh", "issue", "comment", num, "--repo", repo, "--body", body])
        _run(["gh", "issue", "close", num, "--repo", repo, "--reason", "completed"])
        return f"closed #{num}"
    if existing is None:
        url = _run(["gh", "issue", "create", "--repo", repo, "--title", ISSUE_TITLE, "--body", body])
        return f"created {url}"
    num = str(existing["number"])
    _run(["gh", "issue", "edit", num, "--repo", repo, "--body", body])
    return f"updated #{num}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--sync-issue", action="store_true", help="create/update/close the pending-deploy issue")
    parser.add_argument(
        "--summary-file", type=Path, help="append Markdown status to this file (e.g. GITHUB_STEP_SUMMARY)"
    )
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo (or GITHUB_REPOSITORY) is required")

    state = collect_state(args.repo)
    markdown = format_markdown(state, args.repo)
    print(markdown)
    if args.summary_file:
        with args.summary_file.open("a", encoding="utf-8") as fh:
            fh.write(f"## 正式環境後端部署狀態\n\n{markdown}\n")
    if args.sync_issue:
        action = sync_tracking_issue(state, args.repo)
        print(f"[deploy-status] issue action: {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
