# ADR-0027: Retire legacy static site pipeline and read PostgreSQL directly from Paper Watch

## Status
Accepted (2026-11-24, K9 #259). Supersedes ADR-0014 for site generation; refines ADR-0021 by removing the legacy GitHub Pages rollback path and startup full-DB JSON export.

## Context
Since cutover to GutHub (`https://guthub.tw`), PostgreSQL (`app.*` on Supabase) is the single content authority (`data/WRITER=postgres`) served through FastAPI (`apps/api`) and Next.js (`apps/web`). However, the repository still retained the legacy Jinja2/JSON static site generator (`sitegen/`, `templates/`, `static/`, `build.py`, `requirements-site.txt`), its browser parity tests, and GitHub Pages `CI/deploy`:

1. Every pull request rebuilt and browser-tested the retired static site (`CI/test` + `CI/e2e` parity diff), adding ~8 minutes to CI.
2. `apps/web` imported shared CSS/fonts via relative paths reaching into repo-root `static/styles/`.
3. `worker/run.py` had to export the entire PostgreSQL database back into container-local `data/papers.json`, `data/news.json`, and `docs/*.html` on every Paper Watch run solely so `topic_agents.py` and `main.py` could read existing KB context.

After confirming that production runs stably on Next.js + Cloud Run + Supabase and no longer needs a rollback path to the JSON static site, retaining both pipelines creates maintenance drag without operational value.

## Decision
1. **Self-contained frontend assets**: Move shared tokens, base/layout/components/content stylesheets, `archivo-latin.woff2`, and `guthub-logo.png` into `apps/web/`.
2. **Retire static site generation**: Remove `sitegen/`, `templates/`, `static/`, `build.py`, `requirements-site.txt`, legacy static-site browser/link/parity checks (`tools/verify.js`, `tools/e2e.test.js`, `tools/page-errors*.js`, `tools/check_links.py`, `tools/check_next_parity.py`, `tools/measure.js`, `tools/shots.js`, `tools/push-check.js`), static-site pytest suites (`tests/test_sitegen.py`), and the GitHub Pages `deploy` job in `.github/workflows/ci.yml`.
3. **Decouple content schema from `sitegen/`**: Inline the minimal topic registry (`TOPICS`, `ROBOTIC_KEY`, `ROBOTIC_PAGES`) and HTML/slug helpers directly in `import_content.py` so `data/papers.json` + `data/news.json` continue to serve cleanly as local/CI seed fixtures without Jinja2 or `sitegen/`.
4. **Direct PostgreSQL reads for Paper Watch**: Add `load_kb_data()` in `scripts/config.py` that queries `app.topics`, `app.papers`, `app.paper_relations`, and `app.research_commentary` directly when `GUTHUB_CONTENT_DATABASE_URL` is set (falling back to `data/papers.json` for local/unit runs). Use it in `scripts/topic_agents.py`, `scripts/main.py`, and `scripts/check_stale.py`, and remove `import_content.export_kb()` from `worker/run.py` startup.

## Consequences
### Positive
- Eliminates dual-site maintenance, removes Jinja2 from worker and CI installs, and shortens `CI/test` and `CI/e2e`.
- `apps/web` has zero filesystem imports outside its own directory.
- `worker/run.py` starts without writing full-DB JSON/HTML snapshots to disk on every daily scan.
- Unblocks K6 (#256) write-layer HTML sanitization and plain-text normalization without needing dual static-site compatibility.

### Negative / Trade-offs
- Rolling back to the legacy GitHub Pages static site is no longer supported via `content_writer.py` + `build.py` (historical source remains available in git history prior to this commit).
- `scripts/content_store.py` still uses a short-lived temporary workspace during actual publish writes so existing `publish.py` + `validate.py` gates remain transactional; migrating write paths directly to SQL can follow independently in K6/future work.
