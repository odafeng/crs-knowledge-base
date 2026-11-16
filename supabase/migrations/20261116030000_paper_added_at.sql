-- When Paper Watch found a hand-added paper (the date its review issue opened). Lists and feeds date papers by the
-- bot's publish date, else this, else reviewed_at, which stays the date the numbers were last checked.
alter table app.papers add column added_at date check (added_at <= reviewed_at);

create or replace view app.public_papers with (security_invoker = true) as
  select id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line, doi, source,
         reviewed_at, review_status, review_published_at, detail_html, added_at
  from app.papers where withdrawn_at is null;
