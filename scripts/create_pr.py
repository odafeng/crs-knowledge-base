"""Auto-PR utilities (NOT used by the default pipeline).

The default pipeline (main.py) creates GitHub Issues for human review.
This module is retained as an optional utility — if you want to enable
auto-PR or auto-merge in the future, you can import create_prs into
main.py and route high-score papers here instead of to create_issues.

Capabilities:
1. Create a feature branch
2. Generate a full HTML evidence page via Claude API
3. Insert the JS paper object into index.html
4. Apply chart updates to METRICS
5. Create a PR (optionally auto-merge)
"""

import json
import os
import re
import subprocess
import sys

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, GITHUB_TOKEN, INDEX_HTML, PROJECT_ROOT
from topics import TOPIC_DOCS_DIR, TOPIC_JS_VAR, TOPIC_METRICS_VAR, topic_from_str

# Reference HTML for style matching
REFERENCE_HTML = (PROJECT_ROOT / "docs" / "mCRC-BRAF-V600E" / "Kopetz_NEJM_2019_BEACON.html").read_text()

HTML_GEN_PROMPT = """你是一位醫學文獻摘要撰寫專家。請根據以下論文資訊，產出一個完整的 HTML 證據頁面。

## 格式要求
- 必須完全遵循以下參考頁面的 HTML 結構和 CSS 樣式（直接複製 <style> 區塊）
- 包含：<title>, <h1>, .meta 區塊（Authors, Journal, DOI, PMID, Study）, Abstract（Design + Arms）, Key Results（表格）, Conclusions
- 表格需要結構化數據（Endpoint, Experimental, Control）
- 如果 abstract 資訊不足以填滿所有欄位，用合理的推斷或標註 "Data not available"
- 輸出純 HTML，不要 markdown code block

## 參考頁面（請完全複製其 CSS 和結構）
```html
{reference}
```

## 論文資訊
Title: {title}
Authors: {authors}
Journal: {journal} {year}
DOI: {doi}
PMID: {pmid}

Abstract:
{abstract}

請直接輸出完整的 HTML 頁面（從 <!DOCTYPE html> 開始）。"""


def _run_cmd(cmd, cwd=None):
    """Run a shell command. Returns (success, stdout)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd or PROJECT_ROOT)
        if result.returncode != 0:
            print(f"  [WARN] Command failed: {' '.join(cmd)}\n    {result.stderr.strip()}", file=sys.stderr)
            return False, result.stderr
        return True, result.stdout.strip()
    except Exception as e:
        print(f"  [ERROR] {e}", file=sys.stderr)
        return False, ""


def _run_gh(args):
    """Run gh CLI command."""
    env = os.environ.copy()
    if GITHUB_TOKEN:
        env["GH_TOKEN"] = GITHUB_TOKEN
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT, env=env)
        if result.returncode != 0:
            print(f"  [WARN] gh failed: {result.stderr.strip()}", file=sys.stderr)
            return False, result.stderr
        return True, result.stdout.strip()
    except Exception as e:
        print(f"  [ERROR] gh: {e}", file=sys.stderr)
        return False, ""


def generate_html_page(paper):
    """Use Claude API to generate a full HTML evidence page."""
    if not ANTHROPIC_API_KEY:
        print("  [WARN] No API key, using placeholder HTML", file=sys.stderr)
        return _placeholder_html(paper)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = HTML_GEN_PROMPT.format(
        reference=REFERENCE_HTML,
        title=paper.get("title", ""),
        authors=paper.get("authors", ""),
        journal=paper.get("journal", ""),
        year=paper.get("year", ""),
        doi=paper.get("doi", ""),
        pmid=paper.get("pmid", ""),
        abstract=paper.get("abstract", ""),
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    html = next((b.text for b in response.content if hasattr(b, "text")), "")
    # Strip markdown wrapper if present
    if html.startswith("```"):
        html = re.sub(r"^```\w*\n", "", html)
        html = re.sub(r"\n```$", "", html)

    return html


def _placeholder_html(paper):
    """Minimal HTML when no API key is available."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{paper.get("title", "")}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 16px; line-height: 1.7; }}
h1 {{ font-size: 1.3rem; color: #1a365d; border-bottom: 2px solid #3182ce; padding-bottom: 8px; }}
.meta {{ background: #f7fafc; padding: 12px; border-radius: 8px; margin: 12px 0; font-size: 0.88rem; }}
</style>
</head>
<body>
<h1>{paper.get("title", "")}</h1>
<div class="meta">
<strong>Authors:</strong> {paper.get("authors", "")}<br>
<strong>Journal:</strong> <em>{paper.get("journal", "")}</em> {paper.get("year", "")}<br>
<strong>DOI:</strong> <a href="https://doi.org/{paper.get("doi", "")}">{paper.get("doi", "")}</a><br>
<strong>PMID:</strong> {paper.get("pmid", "")}
</div>
<h2>Abstract</h2>
<p>{paper.get("abstract", "")}</p>
</body>
</html>"""


PAPERS_JSON = PROJECT_ROOT / "data" / "papers.json"


def insert_js_object(topic, js_obj):
    """Insert a new paper into data/papers.json.

    Reads JSON, appends to the topic's papers array, writes back.
    No regex. No index.html modification.
    Returns True if successful.
    """
    if not PAPERS_JSON.exists():
        print("  [ERROR] data/papers.json not found", file=sys.stderr)
        return False

    with open(PAPERS_JSON) as f:
        data = json.load(f)

    if topic not in data:
        print(f"  [WARN] Unknown topic in papers.json: {topic}", file=sys.stderr)
        return False

    data[topic]["papers"].append(js_obj)

    with open(PAPERS_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return True


def apply_chart_updates(topic, chart_updates):
    """Apply chart bar additions/updates to data/papers.json metrics.

    No regex. Reads JSON, modifies dict, writes back.
    """
    t = topic_from_str(topic)
    metrics_var = TOPIC_METRICS_VAR.get(t) if t else None
    if not metrics_var or not chart_updates:
        return False

    with open(PAPERS_JSON) as f:
        data = json.load(f)

    metrics = data.get(topic, {}).get("metrics")
    if not metrics:
        return False

    modified = False
    for metric_key, update in chart_updates.items():
        if metric_key not in metrics:
            continue

        action = update.get("action")
        if action == "add":
            bar = update.get("bar", {})
            metrics[metric_key]["bars"].append(bar)
            modified = True
            print(f"  [Chart] Added bar to {metric_key}: {bar.get('label', '?')}")

        elif action == "update":
            match_label = update.get("match_label", "")
            updates = update.get("updates", {})
            for bar in metrics[metric_key]["bars"]:
                if bar.get("label") == match_label:
                    bar.update(updates)
                    modified = True
                    print(f"  [Chart] Updated bar '{match_label}' in {metric_key}")
                    break

        new_max = update.get("new_max")
        if new_max and new_max > metrics[metric_key].get("max", 0):
            metrics[metric_key]["max"] = new_max
            modified = True
            print(f"  [Chart] Updated {metric_key} max → {new_max}")

    if modified:
        with open(PAPERS_JSON, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    return modified


def create_pr_for_paper(paper, dry_run=False):
    """Create a complete PR for a high-relevance paper.

    Steps:
    1. Create branch
    2. Generate HTML evidence page
    3. Insert JS object into index.html
    4. Commit and push
    5. Create PR
    """
    topic = paper.get("topic", "")
    filename = paper.get("ai_suggested_filename", "")
    js_obj = paper.get("ai_suggested_js", {})
    analysis = paper.get("ai_analysis", "")
    bottom_line = paper.get("ai_bottom_line", "")

    if not filename or not js_obj:
        print("  [WARN] Missing filename or JS object, falling back to issue", file=sys.stderr)
        return False

    t = topic_from_str(topic)
    docs_dir = TOPIC_DOCS_DIR.get(t, topic) if t else topic
    js_var = TOPIC_JS_VAR.get(t) if t else None
    metrics_var = TOPIC_METRICS_VAR.get(t) if t else None

    # Branch name from filename
    branch_safe = re.sub(r"[^a-zA-Z0-9_-]", "-", filename.replace(".html", ""))
    branch_name = f"paper/{branch_safe}"

    print(f"[Auto-PR] Creating PR for: {filename}")
    print(f"  Branch: {branch_name}")

    if dry_run:
        print("  [DRY RUN] Would create branch, HTML, and PR")
        return True

    # 1. Create and checkout branch
    _run_cmd(["git", "checkout", "-b", branch_name])

    # 2. Generate HTML page
    print("  Generating HTML evidence page...")
    html_content = generate_html_page(paper)
    docs_path = PROJECT_ROOT / "docs" / docs_dir
    docs_path.mkdir(parents=True, exist_ok=True)
    html_file = docs_path / filename
    html_file.write_text(html_content, encoding="utf-8")
    print(f"  Written: {html_file.relative_to(PROJECT_ROOT)}")

    # 3. Update JS object with file path
    js_obj["file"] = f"docs/{docs_dir}/{filename}"
    if js_var:
        print(f"  Inserting JS object into {js_var}...")
        insert_js_object(topic, js_obj)

    # 3b. Apply chart updates if agent suggested them
    chart_updates = paper.get("ai_chart_updates")
    if chart_updates and metrics_var:
        print(f"  Applying chart updates to {metrics_var}...")
        apply_chart_updates(topic, chart_updates)

    # 4. Commit
    _run_cmd(["git", "add", str(html_file), str(INDEX_HTML)])
    score = paper.get("ai_score", "?")
    commit_msg = (
        f"feat: add {filename}\n\nAuto-generated by paper-watch pipeline.\nRelevance score: {score}/5\n\n{bottom_line}"
    )
    _run_cmd(["git", "commit", "-m", commit_msg])

    # 5. Push branch
    ok, _ = _run_cmd(["git", "push", "-u", "origin", branch_name])
    if not ok:
        print("  [ERROR] Failed to push branch", file=sys.stderr)
        _run_cmd(["git", "checkout", "main"])
        _run_cmd(["git", "branch", "-D", branch_name])
        return False

    # 6. Create PR
    pr_body = f"""## Auto-generated Paper Addition

**Topic**: `{topic}`
**Relevance Score**: {score}/5
**DOI**: [{paper.get("doi", "")}](https://doi.org/{paper.get("doi", "")})

## AI Contextual Analysis
{analysis}

> **Bottom Line**: {bottom_line}

## Changes
- Added evidence page: `docs/{docs_dir}/{filename}`
{f"- Added JS paper object to `{js_var}` in `index.html`" if js_var else ""}

---
Auto-generated and auto-merged by paper-watch pipeline.
"""
    ok, pr_url = _run_gh(
        [
            "pr",
            "create",
            "--title",
            f"[Auto] Add {filename}",
            "--body",
            pr_body,
            "--base",
            "main",
            "--head",
            branch_name,
        ]
    )

    if not ok:
        print("  [ERROR] Failed to create PR", file=sys.stderr)
        _run_cmd(["git", "checkout", "main"])
        return False

    print(f"  Created PR: {pr_url}")

    # 7. Auto-merge the PR
    pr_number = pr_url.rstrip().split("/")[-1] if pr_url else ""
    if pr_number:
        merge_ok, _ = _run_gh(["pr", "merge", pr_number, "--merge", "--delete-branch"])
        if merge_ok:
            print(f"  Auto-merged PR #{pr_number}")
        else:
            print(f"  [WARN] Auto-merge failed for PR #{pr_number}, manual merge needed", file=sys.stderr)

    # Switch back to main and pull merged changes
    _run_cmd(["git", "checkout", "main"])
    _run_cmd(["git", "pull", "--rebase"])

    return True


def create_prs(papers, dry_run=False):
    """Create PRs for a list of score-5 papers."""
    if not papers:
        return

    created = 0
    for paper in papers:
        ok = create_pr_for_paper(paper, dry_run=dry_run)
        if ok:
            created += 1

    print(f"\n[Auto-PR] Created {created}/{len(papers)} PRs.")
