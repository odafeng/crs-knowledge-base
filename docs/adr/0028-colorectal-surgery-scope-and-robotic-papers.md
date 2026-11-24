# ADR-0028: Broaden colorectal surgery tracking and enable auto-published papers for `robotic-surgery`

## Status
Accepted (2026-11-24, K12 #264). Refines ADR-0013 (provenance gate auto-publish scope).

## Context
Previously, the `robotic-surgery` topic differed from all six mCRC topics in two ways:

1. **Card-only presentation**: `data/papers.json` stored `robotic-surgery` content as hand-written HTML cards and timeline entries (`tl_tme`, `tme_cards`, `tl_anast`, `anast_cards`). Because the site did not render `robotic-surgery.papers`, `scripts/publish.py` excluded `robotic-surgery` from `AUTO_PUBLISH_TOPICS` and `import_content.py` rejected any non-empty `robotic-surgery.papers` list. Every surgical paper discovered by Paper Watch was therefore held for manual issue triage even when every number passed the provenance gate.
2. **Narrow search scope**: `scripts/queries.json` restricted `robotic-surgery` PubMed queries and journal filters to robotic/robot-assisted procedures, missing landmark minimally invasive colorectal surgery RCTs such as laparoscopic vs transanal TME (TaTME), complete mesocolic excision (CME), intracorporeal vs extracorporeal anastomosis, anastomotic leak prevention (e.g., ICG fluorescence angiography), and organ-preserving transanal excision.

At the same time, the existing curated overview sections (`/robotic/tme/` and `/robotic/anastomosis/`) remain valuable structured summaries that readers rely on and should not be discarded.

## Decision
1. **Dual overview + `papers` model for `robotic-surgery`**:
   - Keep `robotic_sections` (`tl_tme`, `tme_cards`, `tl_anast`, `anast_cards`) as the curated topic overview on `/robotic/`, `/robotic/tme/`, and `/robotic/anastomosis/`.
   - Enable the standard `papers` array for `robotic-surgery` across the entire stack: add `"robotic-surgery"` to `AUTO_PUBLISH_TOPICS` in `scripts/publish.py`, import and export `robotic-surgery.papers` in `import_content.py`, and render newly published surgical papers on `/robotic/` (using the standard `PaperCard` list) and `/papers/<slug>/` (with `/robotic/` breadcrumbs and topic links).
   - Enable `/feed/robotic.xml` in `feedList()` and `feeds()` once `robotic-surgery` has at least one paper or news story (avoiding empty feeds beforehand).
   - Keep the topic key `robotic-surgery` and URL prefix `/robotic/` unchanged to preserve API contracts, database foreign keys, and existing bookmarks.
2. **Broaden surgical tracking scope**:
   - Expand `scripts/queries.json` (`pubmed_query`, `keywords`, `rss_filter_terms`, `conference_terms`) and `scripts/topic_agents.py` (`_TOPIC_CONTEXTS["robotic-surgery"]`) to cover minimally invasive colorectal surgery RCTs beyond robotic platforms: laparoscopic/robotic TME, TaTME, CME, intracorporeal vs extracorporeal anastomosis, anastomotic leak prevention, sphincter-preserving / transanal excision, and new surgical robotic platforms.
   - Keep `rss_filter_terms` specific to surgical procedures and endpoints (no bare generic colorectal terms) so systemic oncology papers continue routing to their biomarker or `generic-CRS` topics.

## Consequences
### Positive
- Surgical RCTs that pass the provenance gate now auto-publish on the same cadence as mCRC trials instead of stalling permanently in manual review.
- Landmark non-robotic colorectal surgery RCTs (TaTME, CME, intracorporeal anastomosis, leak-prevention trials) enter Paper Watch automatically instead of being filtered out at Layer 1.
- Existing curated TME and anastomosis overview pages, URLs, and API schemas remain 100% backward-compatible.

### Negative / Trade-offs
- Keeping the internal topic key `robotic-surgery` and `/robotic/` route while tracking broader minimally invasive colorectal surgery creates a minor naming mismatch; renaming the key/route later would require a schema enum migration and URL redirects, which is deferred unless the surgical taxonomy expands into multiple sub-topics.
- Broadening the PubMed query to laparoscopic and anastomotic-leak terms increases daily Layer 1 candidate volume for the `robotic-surgery` agent; prompt guidance and existing RCT/landmark scoring criteria are relied upon to filter out small retrospective series.
