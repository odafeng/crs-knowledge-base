# 0011. Conference Highlights Topic Removed

**Status**: Accepted

## Context

A `conference-highlights` topic was added as a dedicated collection for meeting abstracts, indexed by conference and date. However, after removing all Playwright conference scrapers (ADR-0009) and OpenEvidence (ADR-0010), this topic had no reliable automated content source.

The only remaining feed was PubMed's meeting abstract supplement search (JCO, Ann Oncol, DCR `"Meeting Abstract"[pt]`), but this overlapped entirely with what each biomarker-specific topic's agent already catches — the same abstract would be found by both `mCRC-BRAF-V600E` (via keyword match) and `conference-highlights` (via publication type filter).

The 4 entries in the topic were hand-written seed data, not pipeline-generated.

## Decision

Remove the `conference-highlights` topic entirely. Conference abstracts continue to be caught by each biomarker topic's agent during conference season via PubMed supplement search.

## Consequences

- **Positive**: No empty/fake topic on the homepage
- **Positive**: No duplicate abstract processing (was being classified twice)
- **Positive**: 7 topics, each with a clear automated source
- **Negative**: No single place to browse "what happened at ASCO this year" across all topics
- **Negative**: If a conference abstract doesn't match any biomarker keyword, it won't be caught
- **Trade-off**: The user can manually track cross-topic conference highlights if needed; the pipeline won't pretend to do it automatically
