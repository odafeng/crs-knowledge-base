# 0008. Conference-Season-Aware Scheduling

**Status**: Accepted

## Context

Major oncology conferences (ASCO, ESMO) produce a burst of relevant abstracts in a short window. Outside these windows, the CRC literature landscape changes slowly. Running the full pipeline daily year-round is wasteful; running it only weekly risks missing time-sensitive conference content.

## Decision

GitHub Actions cron runs daily, but the `main.py --daily` flag checks if today falls within a conference season window. If not in season, the daily run exits immediately. Regular scans (Tue/Fri) always run regardless of season.

Conference windows are defined in `queries.json` with ±2 weeks buffer. Dates are auto-refreshed quarterly by a Playwright scraper that checks official conference websites.

During conference season, additional data sources activate:
- PubMed supplement search (JCO/Ann Oncol meeting abstracts, 30-day window)
- Medical news site scraping (ASCO Post, OncLive)

## Consequences

- **Positive**: Near-real-time coverage during conference weeks without daily cost year-round
- **Positive**: Buffer windows absorb year-to-year date shifts
- **Positive**: Quarterly auto-refresh from official sites keeps windows accurate
- **Negative**: Hardcoded conference list — adding a new conference requires code change (queries.json + optional scraper)
- **Negative**: "In season" check uses string comparison on MM-DD — doesn't handle year boundaries (conference spanning Dec-Jan would break, but none currently do)
- **Negative**: Daily cron still triggers (and exits) even outside season — minimal but nonzero Actions minutes
