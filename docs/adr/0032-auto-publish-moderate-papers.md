# ADR-0032: Auto-publish score-3 papers without maintainer review

## Status
Accepted (2026-11-28). Amends ADR-0029: score-3/5 papers are no longer only tracked and logged. Tracked in K14 (#308).

## Context
ADR-0029 made scheduled Paper Watch runs fully autonomous for score ≥4/5 papers and dropped score-3/5 papers after recording them. On production, the runs from 2026-11-24 to 2026-11-28 classified 66 candidates across the seven active colorectal topics. None scored ≥4. Ten scored 3 (Moderate: early Phase 1/2 data, pooled analyses). Nothing new had reached the site since 2026-11-21.

The maintainer does not want to review papers by hand, so a review queue for score-3 papers is not an option.

## Decision
- Lower `RELEVANCE_THRESHOLD` in `scripts/config.py` from 4 to 3. Score-3 papers go through the same `publish_or_hold` path as score ≥4 papers: the ADR-0013 provenance gate, up to two ADR-0029 self-repair passes, then publish as `review.status = "auto"`, which the site shows as "AI 未審".
- Ask the classifier for the structured draft (`suggested_js`, `bottom_line`, `suggested_filename`, relations) from score 3 upwards. Without this change, score-3 papers would pass the threshold and then fail the gate for lack of a draft.
- Automatic news keeps its own bar. `news_writer.NEWS_SCORE_THRESHOLD = 4` replaces the shared constant, so a score-3 paper never gets a story.
- A paper that self-repair downgrades below 3 is still held, as before.
- No issues are opened for score-3 papers.

## Consequences
- The site gets new entries on days without a high-impact paper. At the rate seen from 2026-11-24 to 2026-11-28 that is about two a day, though the rate will vary.
- The average entry is weaker. Score-3 papers are preliminary or secondary evidence. Each one still carries the "AI 未審" label, and the home page clinical-insight card still excludes unreviewed papers.
- Every score-3 paper now costs a longer classifier response, a plain-language summary (I2), and possibly repair calls. That adds Anthropic spend roughly in proportion to the extra papers.
- Papers that already scored 3 before this change are tracked, so later scans skip them. They are not backfilled.
- Because nobody reviews the extra entries, a relevance misjudgement by the model reaches readers directly. The numeric provenance gate still blocks unsupported numbers, but it does not judge clinical relevance.
