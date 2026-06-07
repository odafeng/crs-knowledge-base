# 0005. OpenEvidence Guideline Queries via Unofficial Cookie-Based Scraping

**Status**: Accepted (with caveats)

## Context

Agents benefit from knowing "what does the current ASCO guideline say about this biomarker" when scoring papers. OpenEvidence aggregates clinical guidelines with citations. However:

1. OpenEvidence has no public API
2. The Claude.ai remote MCP integration is only available within claude.ai sessions, not via the Anthropic API that our pipeline uses
3. Their website uses DataDome bot protection

## Decision

Use Playwright headless with stored session cookies to scrape OpenEvidence. Cache responses in `data/guidelines/*.json`. Monthly refresh via GitHub Actions (`refresh-guidelines.yml`). Three-tier fallback: OE cache → PubMed guideline search → agent domain knowledge.

## Consequences

- **Positive**: When cache exists, agents get authoritative guideline context at zero latency
- **Positive**: Graceful degradation — system works without OE (just less informed)
- **Negative**: This is NOT an official integration. Using reverse-engineered internal endpoints with stolen cookies
- **Negative**: Cookies expire — requires periodic manual re-login
- **Negative**: OpenEvidence could reasonably object to this usage
- **Negative**: Currently produces zero value — cache is empty because the user hasn't logged in yet
- **Negative**: The code/infrastructure exists but isn't tested end-to-end in production

**Note**: External-facing documentation must NOT describe this as "MCP integration" or "API". It is "unofficial cookie-based Playwright scraping, for private use only."
