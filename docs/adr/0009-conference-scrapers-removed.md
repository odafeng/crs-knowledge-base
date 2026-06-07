# 0009. Conference Scrapers Removed After Testing

**Status**: Accepted (supersedes ADR-0004)

## Context

ADR-0004 proposed Playwright headless scraping for ASCO, ESMO, ASCRS, and ESCP conference abstracts. Additionally, three medical news sites (ASCO Post, OncLive, Cancer Network) were added for same-day conference coverage.

All 7 scrapers were tested against their real websites on 2026-06-07. Results:

| Target | Result | Failure Mode |
|---|---|---|
| ASCO (meetings.asco.org) | ❌ | Flutter SPA — Playwright gets empty body even after 8s wait |
| ESMO (oncologypro.esmo.org) | ❌ | URL returns "Content Unavailable" — site restructured |
| ASCRS (fascrs.org) | ❌ | Timeout + Cloudflare bot protection blocks headless |
| ESCP (escp.eu.com) | ⚠️ | Finds "Abstract Submission" page links, not actual abstracts |
| ASCO Post | ❌ | Search returns homepage articles, not CRC-specific results |
| OncLive | ❌ | 263-char body — JS never renders in headless |
| Cancer Network | ❌ | Same as OncLive |

**None of the scrapers produced usable conference abstract data.**

## Decision

Remove all Playwright-based conference and news scrapers from the pipeline. The sole reliable source for conference content is PubMed's meeting abstract supplement search (JCO, Annals of Oncology, Diseases of the Colon & Rectum publication type "Meeting Abstract"), which catches abstracts 2-4 weeks after presentation.

Playwright remains only for:
- `refresh_guidelines.py` (OpenEvidence scraping, dormant)
- `refresh_conference_dates.py` (quarterly date check from official sites)

These are standalone scheduled workflows, not part of the main paper-watch pipeline.

## Consequences

- **Positive**: Pipeline no longer claims capabilities it doesn't have
- **Positive**: Removed ~550 lines of dead/broken code
- **Positive**: Paper-watch workflow no longer installs Playwright + Chromium (saves ~60s CI time, 400MB)
- **Positive**: Fewer moving parts = fewer silent failures
- **Negative**: 2-4 week lag for conference abstracts (PubMed indexing delay)
- **Negative**: Abstracts that never get PubMed-indexed (some poster presentations) will never be caught
- **Negative**: No same-day conference coverage — user must manually track live conferences
- **Trade-off**: This is the honest state. The previous architecture *looked* like it covered conferences but produced zero results in practice.
