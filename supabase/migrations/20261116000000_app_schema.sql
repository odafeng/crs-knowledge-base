-- B3 #60: content and comment schema (ADR-0016, ADR-0017).
-- Everything lives in `app`, which is not exposed through the Data API. anon, authenticated and service_role get no
-- grants; RLS is enabled with policies only for guthub_api, so an accidental grant or schema exposure still reads
-- nothing. Identity rules (author-only edits, moderation, identity lookup) are enforced by FastAPI, not here.

create schema app;
revoke all on schema app from public;

-- FastAPI connects through a login role that is granted guthub_api; that login role is created per environment (F1).
do $$ begin
  if not exists (select from pg_roles where rolname = 'guthub_api') then
    create role guthub_api nologin;
  end if;
end $$;
grant usage on schema app to guthub_api;
-- Lets the admin role `set role guthub_api` (tests, operations) without inheriting its grants.
grant guthub_api to postgres with inherit false, set true;

create type app.review_status as enum ('auto', 'accepted');
create type app.paper_source as enum ('fulltext', 'abstract', 'secondary', 'curated');
create type app.relation_type as enum ('builds_on', 'supersedes', 'subgroup_of', 'same_regimen', 'contradicts');
create type app.comment_status as enum ('pending', 'published', 'hidden');
create type app.moderation_action as enum ('publish', 'hide', 'reveal_author', 'resolve_report');

-- Content ---------------------------------------------------------------------------------------------------------

create table app.topics (
  key text primary key check (key ~ '^[A-Za-z0-9][A-Za-z0-9-]*$'),
  slug text not null unique,
  label text not null,
  title text not null,
  standard_of_care jsonb not null default '[]' check (jsonb_typeof(standard_of_care) = 'array'),
  robotic_sections jsonb not null default '[]' check (jsonb_typeof(robotic_sections) = 'array')
);

create table app.papers (
  id text primary key check (id <> ''),
  slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]*$'),
  topic_key text not null references app.topics (key),
  year integer not null,
  journal text not null check (journal <> ''),
  study_type text not null check (study_type <> ''),
  n jsonb check (n is null or jsonb_typeof(n) in ('number', 'string', 'null')),
  regimen text not null check (regimen <> ''),
  endpoint text not null check (endpoint <> ''),
  result text not null check (result <> ''),
  bottom_line text not null check (bottom_line <> ''),
  doi text unique check (doi <> ''),
  source app.paper_source not null,
  reviewed_at date not null,
  review_status app.review_status,
  review_published_at date,
  detail_html text not null,
  withdrawn_at timestamptz,
  check ((review_status is null) = (review_published_at is null))
);

create table app.paper_relations (
  paper_id text not null references app.papers (id) on delete cascade,
  target_id text not null references app.papers (id),
  type app.relation_type not null,
  primary key (paper_id, target_id, type),
  check (paper_id <> target_id)
);

create table app.research_commentary (
  id bigint generated always as identity primary key,
  paper_id text not null references app.papers (id) on delete cascade,
  doi text check (doi <> ''),
  pmid text check (pmid <> ''),
  title text not null check (title <> ''),
  journal text not null check (journal <> ''),
  year integer,
  type text not null check (type in ('Editorial', 'Letter', 'News', 'Newspaper Article', 'Comment')),
  summary text not null,
  critique boolean not null,
  new_data boolean not null,
  added_at date not null,
  review_status app.review_status,
  review_published_at date,
  check (doi is not null or pmid is not null),
  check ((review_status is null) = (review_published_at is null)),
  unique (paper_id, doi),
  unique (paper_id, pmid)
);

create table app.news (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]*$'),
  paper_id text not null references app.papers (id),
  published_at date not null,
  headline jsonb not null check (jsonb_typeof(headline) = 'array'),
  dek text not null,
  key jsonb not null check (jsonb_typeof(key) = 'object'),
  figures jsonb not null default '[]' check (jsonb_typeof(figures) = 'array'),
  figure_note text,
  body jsonb not null check (jsonb_typeof(body) = 'array'),
  review_status app.review_status not null,
  review_published_at date,
  withdrawn_at timestamptz
);

-- Accounts and comments -------------------------------------------------------------------------------------------

create table app.accounts (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null check (char_length(btrim(display_name)) between 1 and 80),
  is_admin boolean not null default false,
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table app.comments (
  id uuid primary key default gen_random_uuid(),
  paper_id text not null references app.papers (id),
  -- Private author mapping: never selected by public views. Nulled 90 days after deletion (ADR-0017).
  author_id uuid references app.accounts (id) on delete set null,
  -- Hard ceiling only; the 2000-character policy limit is enforced and tunable in the API.
  body text not null check (char_length(btrim(body)) between 1 and 10000),
  anonymous boolean not null,
  -- Snapshot of the public name for signed comments; always null for anonymous ones.
  display_name text check (display_name <> ''),
  status app.comment_status not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  check (anonymous = (display_name is null)),
  check (author_id is not null or deleted_at is not null)
);
create index comments_paper_idx on app.comments (paper_id, created_at) where deleted_at is null;
create index comments_author_idx on app.comments (author_id, created_at);

create table app.comment_reports (
  id uuid primary key default gen_random_uuid(),
  comment_id uuid not null references app.comments (id),
  reporter_id uuid references app.accounts (id) on delete set null,
  reason text not null check (char_length(btrim(reason)) between 1 and 1000),
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  unique (comment_id, reporter_id)
);

-- Append-only audit of moderation and identity lookups. actor_id has no FK so the record survives account purges.
create table app.moderation_events (
  id bigint generated always as identity primary key,
  comment_id uuid not null references app.comments (id),
  actor_id uuid not null,
  action app.moderation_action not null,
  reason text not null check (btrim(reason) <> ''),
  created_at timestamptz not null default now()
);

-- First comment per account waits for moderation; later ones publish directly (ADR-0017). The caller's status is
-- ignored so the API cannot skip the rule by accident.
create function app.set_initial_comment_status() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.status := case
    when exists (
      select 1 from app.comments c
      where c.author_id = new.author_id and c.status = 'published'
    ) then 'published'::app.comment_status
    else 'pending'::app.comment_status
  end;
  return new;
end $$;

create trigger comments_initial_status
before insert on app.comments
for each row execute function app.set_initial_comment_status();

-- Clears private author mappings 90 days after deletion and removes accounts deleted that long ago. security definer
-- because guthub_api has no DELETE grant; this fixed rule is the only way it can remove accounts.
create function app.purge_deleted_authors() returns void
language sql security definer set search_path = '' as $$
  update app.comments set author_id = null
  where author_id is not null and deleted_at < now() - interval '90 days';
  delete from app.accounts where deleted_at < now() - interval '90 days';
$$;

-- Public views: only visible content, no private columns. security_invoker keeps the caller's grants in force.
create view app.public_papers with (security_invoker = true) as
  select id, slug, topic_key, year, journal, study_type, n, regimen, endpoint, result, bottom_line, doi, source,
         reviewed_at, review_status, review_published_at, detail_html
  from app.papers where withdrawn_at is null;

create view app.public_news with (security_invoker = true) as
  select n.id, n.paper_id, n.published_at, n.headline, n.dek, n.key, n.figures, n.figure_note, n.body,
         n.review_status, n.review_published_at
  from app.news n join app.papers p on p.id = n.paper_id
  where n.withdrawn_at is null and p.withdrawn_at is null;

create view app.public_comments with (security_invoker = true) as
  select c.id, c.paper_id, c.body, c.anonymous, c.display_name, c.created_at, c.updated_at
  from app.comments c join app.papers p on p.id = c.paper_id
  where c.status = 'published' and c.deleted_at is null and p.withdrawn_at is null;

-- Privileges --------------------------------------------------------------------------------------------------------

revoke all on all tables in schema app from public, anon, authenticated, service_role;
revoke all on all functions in schema app from public, anon, authenticated, service_role;
alter default privileges in schema app revoke all on tables from public, anon, authenticated, service_role;
alter default privileges in schema app revoke all on functions from public, anon, authenticated, service_role;

grant select on app.topics, app.papers, app.paper_relations, app.research_commentary, app.news to guthub_api;
grant select on app.public_papers, app.public_news, app.public_comments to guthub_api;
grant select, insert, update on app.accounts, app.comments to guthub_api;
grant select, insert on app.comment_reports to guthub_api;
grant update (resolved_at) on app.comment_reports to guthub_api;
grant select, insert on app.moderation_events to guthub_api;
grant execute on function app.purge_deleted_authors() to guthub_api;

do $$
declare t text;
begin
  foreach t in array array['topics', 'papers', 'paper_relations', 'research_commentary', 'news', 'accounts',
                           'comments', 'comment_reports', 'moderation_events'] loop
    execute format('alter table app.%I enable row level security', t);
    execute format('create policy guthub_api_access on app.%I to guthub_api using (true) with check (true)', t);
  end loop;
end $$;
