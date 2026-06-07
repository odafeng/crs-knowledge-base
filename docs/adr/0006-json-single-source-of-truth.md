# 0006. Migrate Paper Data from Inline JS to data/papers.json

**Status**: Accepted

## Context

Paper data was originally embedded as JS arrays (`const BRAF_PAPERS = [...]`) inside `index.html`. Three backend modules consumed this data via regex:

1. `validate.py` — regex extracted objects to check fields
2. `create_pr.py` — regex found the closing `];` to insert new papers
3. `topic_agents.py` — regex extracted paper context for agent prompts

All three were fragile. A single `}` inside a field value, or a change to quote style (JSON-inserted objects use `"key":` not `key:`), could silently break validation or insertion.

## Decision

Extract all data to `data/papers.json` using Node.js `vm.runInNewContext` (one-time migration with a real JS parser, not regex). Frontend loads via `fetch('./data/papers.json')`. All backend consumers use `json.load()`.

## Consequences

- **Positive**: validate.py, insert_js_object, apply_chart_updates — all zero-regex now
- **Positive**: Single source of truth; frontend and backend read the same file
- **Positive**: Easy to programmatically add/modify papers (just append to list + json.dump)
- **Positive**: Diffable in git (JSON changes are readable)
- **Negative**: `file://` protocol no longer works for local dev (fetch requires HTTP server)
- **Negative**: Frontend needs an extra network request on first load (~3KB gzipped, negligible)
- **Negative**: SW must precache `data/papers.json` — adding a new topic means updating precache list
- **Negative**: Node.js used for one-time migration (not a runtime dependency, but present in repo)
