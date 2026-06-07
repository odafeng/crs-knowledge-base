# 0004. Playwright Headless for Conference Abstract Scraping

**Status**: Accepted

## Context

ASCO (Flutter SPA), ESMO (bot protection), ASCRS, and ESCP don't offer public APIs for their abstract databases. Plain HTTP requests either get blocked (DataDome) or return empty JavaScript shells (Flutter CSR).

PubMed indexes conference abstracts 3-6 months after presentation — too late for a system meant to track "what just happened at ASCO this week."

## Decision

Use Playwright headless Chromium in GitHub Actions to render conference websites and extract abstract data. Four scrapers (ASCO, ESMO, ASCRS, ESCP) run during conference season.

Additionally, search PubMed for JCO/Ann Oncol/DCR "Meeting Abstract" publication type with a 30-day window during conference season.

## Consequences

- **Positive**: Can access content that's otherwise only available via browser rendering
- **Positive**: GitHub Actions provides free Chromium — no infrastructure cost
- **Negative**: Scrapers are inherently brittle — any site redesign breaks them silently
- **Negative**: Adds ~30s to pipeline runtime (Chromium startup + page loads)
- **Negative**: Playwright + Chromium is a heavy dependency (~400MB in CI)
- **Negative**: No contractual right to scrape these sites — terms of service risk
- **Negative**: ASCO Flutter SPA selectors haven't been validated to actually find abstracts (may still return empty)
