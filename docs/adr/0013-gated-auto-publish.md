# 0013. Gated Auto-Publish Replaces Issue-Only Review

**Status**: Accepted (supersedes ADR-0003)

## Context

ADR-0003 routed every paper scoring ≥4 to a GitHub Issue for a human to review and add by hand. In practice the review queue did not get worked through: by 2026-11 there were 14 open paper-watch issues, the oldest from June, and the maintainer does not have time to read each one.

ADR-0003's three reasons against auto-publishing still hold:

1. Not every score-4 paper belongs in the KB.
2. AI-written clinical numbers can be wrong. The 2026-11 review found an unsourced "pCR 組 92%" and "術後全員 MRD 陰性" (#32), an inferred n=51 (#28), and conflicting cCR12 rates (#30). Part of the cause was the pipeline itself: journal-feed abstracts were cut to 500 characters, so the model never saw the results.
3. A public medical KB should not publish unchecked AI content.
4. The earlier auto-merge experiment left a fake "NEJM 2026 Phase 3" page (`Test_NEJM_2026_AutoMergeTest.html`) public for months without anyone noticing.

Removing review entirely was considered and rejected for these reasons. The question was how to cut review time without publishing unverified numbers.

## Decision

Replace "review everything" with a deterministic gate. Papers that pass are published automatically and labelled as unreviewed; papers that fail go to an issue as before.

**Paper gate** (`provenance.evaluate_paper_gate`); all must hold:

- AI classification succeeded and produced a KB entry
- The PubMed abstract is complete (`abstract_status == "full"`)
- The topic renders a papers list (not `robotic-surgery`, which uses hand-written cards)
- Every evidence item is `source: abstract` and its quote is a literal substring of the abstract
- Every number in the entry's `n`, `result` and `bottomLine` appears in the abstract and is covered by an evidence claim
- The resulting `papers.json` passes `validate_data()` (unique id / DOI, known studyType, relations, files)

**Commentary gate** (`provenance.evaluate_commentary_gate`): PubMed's own CommentOn link maps it to the KB trial (not an AI guess), it has no new data, and its summary adds no numbers absent from its abstract.

**Publishing** (`publish.py`): entries carry `review: {status, publishedAt}`. `auto` = gate-passed, never seen by a human. `accepted` = a reviewer added the `accepted` label to a held issue. Hand-curated entries have no `review` field. Model-written strings are HTML-escaped; the site shows "AI 自動整理・未經人工審核" on auto entries.

**Human controls**:

- Held items: add `accepted` to the issue → `paper-accept.yml` publishes it (`accepted`). For commentary, only ticked items are published.
- Near misses (#218): papers scored 3/5, one under the threshold, are listed per run in one `paper-digest` issue. The threshold stays at 4, because a 3/5 paper has no KB entry to publish and a lower threshold would also loosen auto-publishing. The maintainer ticks papers and adds `accepted`; the next Paper Watch run re-classifies the ticked ones through `main.py --review` (#214), which drafts an entry whatever the score, and opens an ordinary held issue for each. `content-requests` skips digests because it has no Anthropic key. The cost is one more classification per ticked paper and up to a day's wait for the daily schedule.
- Anything published by the bot: Actions → `Unpublish` with the paper id or commentary DOI. Hand-curated entries are refused.
- Writes to `main` from these workflows share one concurrency group. Because pushes made with `GITHUB_TOKEN` do not trigger workflows, each one dispatches `ci.yml`, which validates and deploys.

## Consequences

- **Positive**: Papers whose numbers are all verifiable against the abstract reach the site without anyone's time.
- **Positive**: The gate is code, not model self-report: a fabricated number fails because it is not in the abstract, whatever the model claims.
- **Positive**: Held issues explain why they were held and need one label to publish.
- **Negative**: The gate checks numbers, not interpretation. A correct number attached to the wrong arm or endpoint passes. The "未經人工審核" label and Unpublish are the mitigations.
- **Negative**: Only the abstract counts as a source. Papers whose key results are only in the full text, or in conference abstracts without a PubMed abstract, are always held.
- **Negative**: `robotic-surgery` is never auto-published until its cards move to structured data.
- **Negative**: The bot now writes to `main` directly. Branch protection that requires PRs would block it; this is a deliberate trade-off.
