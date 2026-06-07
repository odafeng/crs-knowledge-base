"""Auto-PR creation for score-5 papers.

For practice-changing papers (score 5), automatically:
1. Create a feature branch
2. Generate a full HTML evidence page via Claude API
3. Insert the JS paper object into index.html
4. Create a PR for review
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=cwd or PROJECT_ROOT
        )
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
        result = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT, env=env
        )
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

    html = response.content[0].text
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
<title>{paper.get('title', '')}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 16px; line-height: 1.7; }}
h1 {{ font-size: 1.3rem; color: #1a365d; border-bottom: 2px solid #3182ce; padding-bottom: 8px; }}
.meta {{ background: #f7fafc; padding: 12px; border-radius: 8px; margin: 12px 0; font-size: 0.88rem; }}
</style>
</head>
<body>
<h1>{paper.get('title', '')}</h1>
<div class="meta">
<strong>Authors:</strong> {paper.get('authors', '')}<br>
<strong>Journal:</strong> <em>{paper.get('journal', '')}</em> {paper.get('year', '')}<br>
<strong>DOI:</strong> <a href="https://doi.org/{paper.get('doi', '')}">{paper.get('doi', '')}</a><br>
<strong>PMID:</strong> {paper.get('pmid', '')}
</div>
<h2>Abstract</h2>
<p>{paper.get('abstract', '')}</p>
</body>
</html>"""


def insert_js_object(topic, js_obj):
    """Insert a new paper JS object into the appropriate array in index.html.

    Returns True if successful.
    """
    t = topic_from_str(topic)
    var_name = TOPIC_JS_VAR.get(t) if t else None
    if not var_name:
        print(f"  [WARN] No JS array mapping for topic: {topic}", file=sys.stderr)
        return False
    html = INDEX_HTML.read_text(encoding="utf-8")

    # Format the JS object
    js_str = json.dumps(js_obj, indent=2, ensure_ascii=False)
    # Convert JSON to JS style (unquote keys, single quotes for values)
    # Keep it as valid JSON-in-JS for simplicity — it's valid either way
    js_entry = "  " + js_str.replace("\n", "\n  ")

    # Find the closing ]; of the array and insert before it
    pattern = rf"(const {var_name}\s*=\s*\[.*?)(^\];)"
    match = re.search(pattern, html, re.DOTALL | re.MULTILINE)
    if not match:
        print(f"  [ERROR] Could not find {var_name} array in index.html", file=sys.stderr)
        return False

    # Insert new entry before the closing ];
    insertion_point = match.start(2)
    new_html = html[:insertion_point] + js_entry + ",\n" + html[insertion_point:]
    INDEX_HTML.write_text(new_html, encoding="utf-8")
    return True


def apply_chart_updates(topic, chart_updates):
    """Apply chart bar additions/updates to the METRICS object in index.html.

    chart_updates is a dict like:
    {
      "mOS": {"action": "add", "bar": {...}, "new_max": 35},
      "ORR": {"action": "update", "match_label": "EC+\\nFOLFIRI", "updates": {"val": 64.4}}
    }
    """
    t = topic_from_str(topic)
    metrics_var = TOPIC_METRICS_VAR.get(t) if t else None
    if not metrics_var or not chart_updates:
        return False

    html = INDEX_HTML.read_text(encoding="utf-8")
    modified = False

    for metric_key, update in chart_updates.items():
        action = update.get("action")

        if action == "add":
            bar = update.get("bar", {})
            bar_str = json.dumps(bar, ensure_ascii=False)

            # Find the bars array for this metric within the METRICS var
            # Pattern: metric_key: { ... bars: [ ... ] }
            # We need to find the closing ] of the bars array for this metric
            metric_pattern = rf'({metric_key}\s*:\s*\{{[^}}]*bars\s*:\s*\[)(.*?)(\s*\])'
            match = re.search(metric_pattern, html, re.DOTALL)
            if match:
                # Insert new bar before the closing ]
                html = html[:match.end(2)] + ",\n      " + bar_str + html[match.end(2):]
                modified = True
                print(f"  [Chart] Added bar to {metric_key}: {bar.get('label', '?')}")

        elif action == "update":
            match_label = update.get("match_label", "")
            updates = update.get("updates", {})
            if match_label and updates:
                # Find the bar with this label and update its values
                # Use a simple approach: find the bar object containing this label
                escaped_label = re.escape(match_label)
                bar_pattern = rf"(\{{\s*label\s*:\s*'{escaped_label}'[^}}]*)\}}"
                match = re.search(bar_pattern, html)
                if match:
                    bar_text = match.group(1)
                    new_bar_text = bar_text
                    for key, value in updates.items():
                        if isinstance(value, bool):
                            val_str = "true" if value else "false"
                        elif value is None:
                            val_str = "null"
                        elif isinstance(value, (int, float)):
                            val_str = str(value)
                        else:
                            val_str = f"'{value}'"

                        # Replace or append the key
                        key_pattern = rf"{key}\s*:\s*[^,}}]+"
                        if re.search(key_pattern, new_bar_text):
                            new_bar_text = re.sub(key_pattern, f"{key}:{val_str}", new_bar_text)
                        else:
                            new_bar_text += f", {key}:{val_str}"

                    html = html.replace(bar_text, new_bar_text)
                    modified = True
                    print(f"  [Chart] Updated bar '{match_label}' in {metric_key}")

        # Update max if specified
        new_max = update.get("new_max")
        if new_max:
            max_pattern = rf"({metric_key}\s*:\s*\{{[^}}]*max\s*:\s*)(\d+)"
            match = re.search(max_pattern, html)
            if match:
                current_max = int(match.group(2))
                if new_max > current_max:
                    html = html[:match.start(2)] + str(new_max) + html[match.end(2):]
                    modified = True
                    print(f"  [Chart] Updated {metric_key} max: {current_max} → {new_max}")

    if modified:
        INDEX_HTML.write_text(html, encoding="utf-8")

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
        print(f"  [WARN] Missing filename or JS object, falling back to issue", file=sys.stderr)
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
        print(f"  [DRY RUN] Would create branch, HTML, and PR")
        return True

    # 1. Create and checkout branch
    _run_cmd(["git", "checkout", "-b", branch_name])

    # 2. Generate HTML page
    print(f"  Generating HTML evidence page...")
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
    commit_msg = f"feat: add {filename}\n\nAuto-generated by paper-watch pipeline.\nRelevance score: {score}/5\n\n{bottom_line}"
    _run_cmd(["git", "commit", "-m", commit_msg])

    # 5. Push branch
    ok, _ = _run_cmd(["git", "push", "-u", "origin", branch_name])
    if not ok:
        print(f"  [ERROR] Failed to push branch", file=sys.stderr)
        _run_cmd(["git", "checkout", "main"])
        _run_cmd(["git", "branch", "-D", branch_name])
        return False

    # 6. Create PR
    pr_body = f"""## Auto-generated Paper Addition

**Topic**: `{topic}`
**Relevance Score**: {score}/5
**DOI**: [{paper.get('doi', '')}](https://doi.org/{paper.get('doi', '')})

## AI Contextual Analysis
{analysis}

> **Bottom Line**: {bottom_line}

## Changes
- Added evidence page: `docs/{docs_dir}/{filename}`
{f"- Added JS paper object to `{js_var}` in `index.html`" if js_var else ""}

---
Auto-generated and auto-merged by paper-watch pipeline.
"""
    ok, pr_url = _run_gh([
        "pr", "create",
        "--title", f"[Auto] Add {filename}",
        "--body", pr_body,
        "--base", "main",
        "--head", branch_name,
    ])

    if not ok:
        print(f"  [ERROR] Failed to create PR", file=sys.stderr)
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
