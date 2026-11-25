# ADR-0029: Autonomous Paper Watch with bounded AI self-repair and zero routine review issues

## Status
Accepted (2026-11-25). Refines ADR-0013 (auto-publish provenance gate) and supersedes routine opening of `paper-digest`, `new-paper`, and `commentary-review` issues during scheduled scans.

## Context
Under ADR-0013 and `#218`, scheduled Paper Watch runs opened three kinds of GitHub issues for maintainer triage:

1. `paper-digest` issues listing score-3/5 papers for manual picking (`#276`, `#277`).
2. `new-paper` review issues for score ≥4/5 papers that failed the provenance gate (`scripts/provenance.py`) or `validate_data()`.
3. `commentary-review` issues for editorials/letters matched by AI or containing new data.

In practice, routine manual issue review creates backlog without adding safety over the automated provenance gate:
- Most score ≥4/5 gate failures are mechanical formatting or citation mistakes on the first model pass (e.g., citing an inferred sample size, forgetting an `evidence` entry for a number in `regimen`/`endpoint`, or writing `Phase 3 RCT` when the abstract omits randomisation) that can be fixed deterministically by re-grounding strictly against the verbatim PubMed abstract.
- Score-3/5 papers were already judged below the clinical-impact threshold; listing them for manual review adds notification noise.

At the same time, we MUST keep the provenance gate intact so unverified numbers never reach clinicians, and we MUST keep the `"auto"` ("AI 未審") disclosure on auto-published pages so readers always know entries were generated from PubMed abstracts without human review.

## Decision
1. **Bounded AI self-repair (`scripts/classify.py::repair_paper`)**:
   - When a score ≥4/5 paper with a full PubMed abstract fails `evaluate_paper_gate()` or `publish_paper()` validation, feed the exact `gate_reasons`, prior draft, and verbatim PubMed abstract back to the classifier (with research tools disabled so only the verbatim abstract can be cited) for up to `MAX_REPAIR_ATTEMPTS = 2` attempts.
   - Re-evaluate `evaluate_paper_gate()` and `publish_paper()` after each attempt. If the repaired entry passes, auto-publish it with `review.status = "auto"` (preserving the "AI 未審" badge and sitemap exclusion).
   - Skip repair immediately when unrepairable (missing/truncated abstract, parse failure, unsupported topic, or model downgrades score below threshold).
2. **Stop opening routine review issues during scheduled scans (`scripts/main.py::run_pipeline`)**:
   - Do not open `paper-digest` issues for score-3/5 papers; track them and log the count.
   - Do not open `new-paper` issues for papers that remain unpublishable after bounded self-repair; log their `gate_reasons` and track them so they are not retried indefinitely.
   - Do not open `commentary-review` issues for commentary that fails `evaluate_commentary_gate()`; continue auto-publishing PubMed `CommentOn`-verified commentary and log skipped items.
   - Only send maintainer LINE notifications for papers actually published.
3. **Preserve manual override paths**:
   - Keep `main.py --review PMID --topic ...`, `review_picks()`, and `accept_issue.py` working so the maintainer can still manually pull in any specific paper or act on previously opened digest issues if desired.

## Consequences
### Positive
- Zero routine GitHub issues to triage; Paper Watch runs fully hands-off.
- Higher auto-publish success rate on legitimate score ≥4/5 papers whose first draft had a minor citation or `studyType` slip, without loosening the numeric provenance gate.
- Published entries remain transparently labelled as AI-generated (`review.status = "auto"`).

### Negative / Trade-offs
- Score ≥4/5 papers whose PubMed abstract is genuinely missing or truncated (or still unverified after 2 repair passes) are skipped and logged in Cloud Run rather than queued in GitHub Issues, so they will not appear on the site unless manually added via `--review`.
- Each repair attempt adds 1 Claude API call (capped at 2 per failing score ≥4/5 paper, with research tools disabled).
