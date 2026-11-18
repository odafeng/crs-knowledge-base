-- I1 #190: a Traditional Chinese summary per paper, so a reader sees at a glance what the study asked, in whom,
-- against what, what it found and what to be careful about (ADR-0025). Written by scripts/paper_summary.py from the
-- PubMed abstract and kept only when every number traces to the sources; reviewedAt stays null until the maintainer
-- marks the paper reviewed. The shape is checked by scripts/validate.py, as the rest of papers.json is.

alter table app.papers add column summary jsonb check (summary is null or jsonb_typeof(summary) = 'object');

create or replace view app.public_papers with (security_invoker = true) as
  select id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line, doi, source,
         reviewed_at, review_status, review_published_at, detail_html, added_at, summary
  from app.papers where withdrawn_at is null;

-- scripts/paper_summary.py writes through the content writer like every other content change.
alter table app.publish_events drop constraint publish_events_action_check;
alter table app.publish_events add constraint publish_events_action_check
  check (action in ('publish_paper', 'publish_commentary', 'unpublish', 'review', 'summarize'));
