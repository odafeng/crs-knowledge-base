-- K7 #257: index keyword search with PostgreSQL pg_trgm instead of scanning and expanding JSONB on every request.
-- Both app.papers and app.news keep a lowercased search_text column maintained by triggers, indexed with partial GIN
-- trigram indexes matching the app.public_* views.

create extension if not exists pg_trgm with schema extensions;

alter table app.papers add column search_text text not null default '';
alter table app.news add column search_text text not null default '';

create or replace function app.paper_search_text(
  p_id text,
  p_regimen text,
  p_journal text,
  p_year integer,
  p_topic_key text,
  p_study_type text,
  p_endpoint text,
  p_result text,
  p_bottom_line text
) returns text
language sql stable set search_path = '' as $$
  select lower(concat_ws(
    ' ',
    p_id,
    p_regimen,
    p_journal,
    p_year::text,
    (select t.label from app.topics t where t.key = p_topic_key),
    p_study_type,
    p_endpoint,
    p_result,
    p_bottom_line
  ));
$$;

create or replace function app.news_search_text(
  p_headline jsonb,
  p_dek text,
  p_body jsonb
) returns text
language sql stable set search_path = '' as $$
  select lower(concat_ws(
    ' ',
    (select string_agg(part, '' order by ord) from jsonb_array_elements_text(p_headline) with ordinality h(part, ord)),
    p_dek,
    (select string_agg(s->>'text', ' ') from jsonb_array_elements(p_body) s)
  ));
$$;

create or replace function app.set_paper_search_text() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.search_text := app.paper_search_text(
    new.id, new.regimen, new.journal, new.year, new.topic_key,
    new.study_type, new.endpoint, new.result, new.bottom_line
  );
  return new;
end $$;

create or replace function app.set_news_search_text() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.search_text := app.news_search_text(new.headline, new.dek, new.body);
  return new;
end $$;

create or replace function app.refresh_topic_paper_search_text() returns trigger
language plpgsql set search_path = '' as $$
begin
  update app.papers p
  set search_text = app.paper_search_text(
    p.id, p.regimen, p.journal, p.year, p.topic_key,
    p.study_type, p.endpoint, p.result, p.bottom_line
  )
  where p.topic_key = new.key;
  return new;
end $$;

create trigger papers_search_text_sync
before insert or update of id, topic_key, regimen, journal, year, study_type, endpoint, result, bottom_line
on app.papers
for each row execute function app.set_paper_search_text();

create trigger news_search_text_sync
before insert or update of headline, dek, body
on app.news
for each row execute function app.set_news_search_text();

create trigger topics_label_search_text_sync
after update of label on app.topics
for each row when (old.label is distinct from new.label)
execute function app.refresh_topic_paper_search_text();

-- Backfill existing rows before creating the GIN trigram indexes.
update app.papers p
set search_text = app.paper_search_text(
  p.id, p.regimen, p.journal, p.year, p.topic_key,
  p.study_type, p.endpoint, p.result, p.bottom_line
);

update app.news n
set search_text = app.news_search_text(n.headline, n.dek, n.body);

create index papers_search_text_trgm_idx
  on app.papers using gin (search_text extensions.gin_trgm_ops)
  where withdrawn_at is null;

create index news_search_text_trgm_idx
  on app.news using gin (search_text extensions.gin_trgm_ops)
  where withdrawn_at is null;

-- Expose search_text at the end of the public views so /search filters through the GIN indexes without changing
-- existing column positions.
create or replace view app.public_papers with (security_invoker = true) as
  select id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line, doi, source,
         reviewed_at, review_status, review_published_at, detail_html, added_at, summary, search_text
  from app.papers where withdrawn_at is null;

create or replace view app.public_news with (security_invoker = true) as
  select n.id, n.paper_id, n.published_at, n.headline, n.dek, n.key, n.figures, n.figure_note, n.body,
         n.review_status, n.review_published_at, n.search_text
  from app.news n join app.papers p on p.id = n.paper_id
  where n.withdrawn_at is null and p.withdrawn_at is null;
