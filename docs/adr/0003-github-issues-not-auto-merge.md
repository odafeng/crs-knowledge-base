# 0003. Score ≥4 Creates GitHub Issues, Not Auto-Merge

**Status**: Accepted (supersedes earlier auto-merge design)

## Context

The pipeline initially auto-created PRs and auto-merged them for score ≥4 papers. This was changed because:

1. Score 4 ("high-impact") includes single-arm Phase 2, subgroup analyses, and conference abstracts — not all warrant immediate addition to a clinical reference tool
2. AI-generated HTML pages and JS objects could contain factual errors in clinical numbers
3. A public medical knowledge base auto-publishing AI-assessed content without human review is an unacceptable risk/trust trade-off

## Decision

All papers scoring ≥4 create a GitHub Issue (with AI analysis, suggested JS object, and suggested chart updates) + LINE push notification. The human (surgeon) reviews and decides whether to incorporate.

`create_pr.py` is retained as dormant utility code but is NOT called by `main.py`. Contract tests enforce this boundary.

## Consequences

- **Positive**: No clinical content published without human review
- **Positive**: AI suggestions (JS object, filename, chart updates) are in the Issue body — easy to copy-paste if approved
- **Positive**: Parse failures also go to review queue (not silently dropped)
- **Negative**: Requires manual effort to actually add approved papers to `data/papers.json`
- **Negative**: During high-volume periods (ASCO with 50+ papers), the Issue backlog may grow faster than review capacity
- **Negative**: 371 lines of create_pr.py are dead code (tech debt)
