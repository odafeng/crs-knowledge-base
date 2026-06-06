"""Layer 3: Create GitHub Issues for high-relevance candidate papers."""

import argparse
import json
import subprocess
import sys

from config import GITHUB_REPO, GITHUB_TOKEN


def _run_gh(args, input_text=None):
    """Run a gh CLI command. Returns (success, stdout)."""
    cmd = ["gh"] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            input=input_text,
            env={"GH_TOKEN": GITHUB_TOKEN, "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"}
            if GITHUB_TOKEN else None,
        )
        if result.returncode != 0:
            print(f"  [WARN] gh command failed: {result.stderr.strip()}", file=sys.stderr)
            return False, result.stderr
        return True, result.stdout.strip()
    except FileNotFoundError:
        print("  [ERROR] gh CLI not found. Install: https://cli.github.com", file=sys.stderr)
        return False, ""
    except subprocess.TimeoutExpired:
        print("  [WARN] gh command timed out", file=sys.stderr)
        return False, ""


def _ensure_labels(labels):
    """Create labels if they don't exist (idempotent)."""
    label_colors = {
        "new-paper": "0e8a16",
        "priority:high": "b60205",
        "topic:braf-v600e": "d93f0b",
        "topic:kras-g12c": "e99695",
        "topic:msi-h": "0075ca",
        "topic:her2": "7057ff",
        "topic:ras-wt": "fbca04",
        "topic:robotic": "006b75",
    }
    for label, color in label_colors.items():
        if label in labels:
            _run_gh(["label", "create", label, "--color", color, "--force"])


def _topic_to_label(topic):
    """Convert topic key to GitHub label."""
    mapping = {
        "mCRC-BRAF-V600E": "topic:braf-v600e",
        "mCRC-KRAS-G12C": "topic:kras-g12c",
        "mCRC-MSI-H": "topic:msi-h",
        "mCRC-HER2": "topic:her2",
        "mCRC-RAS-wt": "topic:ras-wt",
        "robotic-surgery": "topic:robotic",
    }
    return mapping.get(topic, "")


def format_issue_body(paper):
    """Format a paper into a GitHub Issue body (markdown)."""
    score = paper.get("ai_score", "?")
    analysis = paper.get("ai_analysis", "N/A")
    bottom_line = paper.get("ai_bottom_line", "")

    lines = []
    lines.append(f"**Topic**: `{paper.get('topic', '')}`")
    lines.append(f"**Relevance Score**: {score}/5")
    lines.append(f"**Source**: {paper.get('source', 'pubmed').upper()}")
    lines.append(f"**Journal**: {paper.get('journal', '')} | **Year**: {paper.get('year', '')}")

    if paper.get("doi"):
        lines.append(f"**DOI**: [{paper['doi']}](https://doi.org/{paper['doi']})")
    if paper.get("pmid"):
        lines.append(f"**PMID**: {paper['pmid']}")
    if paper.get("link"):
        lines.append(f"**Link**: {paper['link']}")

    lines.append("")
    lines.append("## AI Contextual Analysis")
    lines.append(analysis)

    if bottom_line:
        lines.append("")
        lines.append(f"> **Bottom Line**: {bottom_line}")

    if paper.get("ai_suggested_js"):
        lines.append("")
        lines.append("## Suggested JS Object")
        lines.append("```javascript")
        lines.append(json.dumps(paper["ai_suggested_js"], indent=2, ensure_ascii=False))
        lines.append("```")

    if paper.get("ai_suggested_filename"):
        lines.append("")
        lines.append(f"## Suggested Filename")
        lines.append(f"`docs/{paper.get('topic', 'unknown')}/{paper['ai_suggested_filename']}`")

    if paper.get("abstract"):
        lines.append("")
        lines.append("<details><summary>Original Abstract</summary>")
        lines.append("")
        lines.append(paper["abstract"][:2000])
        lines.append("")
        lines.append("</details>")

    return "\n".join(lines)


def create_issues(papers, dry_run=False):
    """Create GitHub Issues for a list of classified papers."""
    if not papers:
        print("[Issues] No papers to create issues for.")
        return

    # Collect all labels we'll need
    all_labels = {"new-paper", "priority:high"}
    for p in papers:
        lbl = _topic_to_label(p.get("topic", ""))
        if lbl:
            all_labels.add(lbl)

    if not dry_run:
        _ensure_labels(all_labels)

    created = 0
    for paper in papers:
        title_short = paper.get("title", "Untitled")
        if len(title_short) > 100:
            title_short = title_short[:97] + "..."

        issue_title = f"[New Paper] {title_short}"
        body = format_issue_body(paper)
        labels = ["new-paper"]
        topic_label = _topic_to_label(paper.get("topic", ""))
        if topic_label:
            labels.append(topic_label)

        score = paper.get("ai_score")
        if score and score >= 5:
            labels.append("priority:high")

        if dry_run:
            print(f"\n{'='*60}")
            print(f"ISSUE: {issue_title}")
            print(f"LABELS: {', '.join(labels)}")
            print(f"{'='*60}")
            print(body[:500])
            print("...")
            created += 1
            continue

        label_args = []
        for l in labels:
            label_args.extend(["--label", l])

        ok, url = _run_gh(
            ["issue", "create", "--title", issue_title] + label_args + ["--body", body]
        )
        if ok:
            print(f"  Created issue: {url}")
            created += 1
        else:
            print(f"  [ERROR] Failed to create issue for: {title_short}", file=sys.stderr)

    print(f"\n[Issues] Created {created}/{len(papers)} issues.")


def main():
    parser = argparse.ArgumentParser(description="Create GitHub Issues for new papers")
    parser.add_argument("--input", help="JSON file with classified papers (default: stdin)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            papers = json.load(f)
    else:
        papers = json.load(sys.stdin)

    create_issues(papers, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
