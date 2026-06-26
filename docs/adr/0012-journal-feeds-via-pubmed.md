# 0012. Journal Feeds via PubMed Instead of Publisher RSS

**Status**: Accepted

## Context

Layer 1b (`fetch_rss.py`) scraped 8 publisher RSS feeds directly (NEJM, JCO,
Lancet Oncol, Nature Medicine, Annals of Oncology, JAMA Oncology, Annals of
Surgery, BJS) to catch high-impact-journal colorectal papers that a narrow
biomarker keyword query might miss.

Inspection of the live Paper Watch logs showed **every single feed was failing**:

| Feed | Failure |
|------|---------|
| NEJM, Lancet Oncol, Annals of Surgery | HTTP 403 Forbidden (publisher bot-blocking) |
| Annals of Oncology | HTTP 410 Gone (feed discontinued) |
| JAMA Oncology, BJS | HTTP 404 Not Found (feed URL changed) |
| JCO, Nature Medicine | reachable but returned 0 entries |

`_fetch_feed` swallowed each error as a `[WARN]` and returned `[]`, so the whole
RSS layer contributed **zero candidates** while the workflow still reported
success — a silent, months-long degradation hidden behind a green checkmark.

Publisher feeds are fundamentally fragile for an automated client: feeds get
bot-blocked, moved, or discontinued, and the URLs cannot be reliably verified
without live access to each publisher. Meanwhile NCBI E-utilities (PubMed) —
already used successfully by Layer 1a and the conference-supplement search — is
not bot-blocked, indexes all of these journals, and supports journal-scoped
queries (`"N Engl J Med"[Journal]`).

## Decision

Re-point the journal feeds through PubMed. Each `rss_feeds` entry now carries a
`pubmed_journal` (ISO abbreviation) instead of a `url`. `fetch_rss` queries
`("<journal>"[Journal]) AND <colorectal filter>` over the same `reldate` window,
reusing the proven `esearch`/`efetch` plumbing, then assigns each article to a
topic by keyword match (unchanged behaviour). The public function name
`fetch_rss` is kept for pipeline/CLI compatibility.

To prevent silent degradation from recurring, the layer now distinguishes
"fetched OK, no new papers" (healthy) from "fetch errored" (unhealthy): if
**every** journal query errors, it raises `AllFeedsFailedError` and `main.py`
exits non-zero so the workflow turns **red**. A partial failure logs a warning
and continues.

## Consequences

- **Positive**: Journal discovery works again, from a single non-blocked source
- **Positive**: 8 flaky external dependencies collapse to one already-trusted one
- **Positive**: Total outages now fail loudly instead of silently passing
- **Positive**: Fully unit-testable (mock `esearch`/`efetch`) — no live HTTP
- **Negative**: PubMed indexing lags a publisher's own feed by days for some journals
- **Negative**: Ahead-of-print papers not yet in PubMed are caught a little later
- **Trade-off**: Slight recency loss in exchange for a feed that actually runs
