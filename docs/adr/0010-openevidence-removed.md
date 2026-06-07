# 0010. OpenEvidence Integration Removed

**Status**: Accepted (supersedes ADR-0005)

## Context

ADR-0005 proposed using OpenEvidence for guideline queries via Playwright headless scraping with stored cookies. After implementation and testing:

1. **Cookie export worked** — Cookie-Editor extension successfully exported session cookies
2. **Session authentication worked** — Playwright could load the OE homepage as a logged-in user (verified by seeing conversation history)
3. **Question submission failed** — DataDome bot protection intercepted the form submission from headless Chromium, blocking the actual query

The htlin222/openevidence-mcp relay architecture (browser extension + localhost relay) could bypass DataDome, but requires a real browser to stay open — defeating the purpose of CI automation.

## Decision

Remove the entire OpenEvidence integration:
- `scripts/refresh_guidelines.py` (230 lines)
- `.github/workflows/refresh-guidelines.yml`
- `data/guidelines/` cache directory
- OE cache logic in `agent_tools.py` (~120 lines)
- `OE_COOKIES_JSON` secret reference

The `query_guidelines` agent tool is retained but simplified to PubMed-only: it searches for guideline/consensus articles using PubMed publication type filters.

## Consequences

- **Positive**: Removed ~380 lines of code that never produced value
- **Positive**: One fewer GitHub Actions workflow to maintain
- **Positive**: No more misleading "guideline cache" infrastructure that was always empty
- **Positive**: System only claims capabilities it actually has
- **Negative**: Agents lose access to synthesized guideline summaries (PubMed returns raw articles, not curated answers)
- **Negative**: If OpenEvidence ever offers a public API, we'd rebuild from scratch
- **Trade-off**: PubMed guideline search is less powerful than OE's synthesized answers, but it actually works
