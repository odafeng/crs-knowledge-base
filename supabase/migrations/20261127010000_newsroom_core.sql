-- N1 #286 (ADR-0031): Event-centric Newsroom core schema, versioned revisions, claim-evidence links,
-- multi-domain event taxonomy, audit trail, run telemetry, public views, and strict RLS isolation.
-- Legacy app.news (paper-based news stories) remains 100% untouched.

create table app.news_source_registry (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]*$'),
  name text not null check (char_length(btrim(name)) > 0),
  source_type text not null check (
    source_type in ('regulatory', 'society', 'trial_registry', 'guideline', 'journal', 'intake_repo')
  ),
  base_url text not null check (base_url ~ '^https://'),
  terms_reviewed_at date not null,
  poll_interval_minutes integer not null default 360 check (poll_interval_minutes >= 15),
  trust_tier text not null check (trust_tier in ('tier1', 'tier2', 'tier3')),
  enabled boolean not null default false,
  config jsonb not null default '{}'::jsonb,
  last_success_at timestamptz,
  last_error text,
  last_error_at timestamptz,
  updated_at timestamptz not null default now()
);

create table app.news_ingest_batches (
  id uuid primary key default gen_random_uuid(),
  producer text not null check (char_length(btrim(producer)) > 0),
  batch_id text not null check (char_length(btrim(batch_id)) > 0),
  schema_version text not null check (schema_version in ('1.0', '1.1')),
  source_repo text,
  source_issue_number integer,
  source_author text,
  payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
  test_mode boolean not null default true,
  publish_allowed boolean not null default false,
  status text not null check (status in ('ingested', 'isolated_test', 'conflict', 'rejected')),
  item_count integer not null default 0 check (item_count >= 0),
  raw_payload jsonb not null,
  error_detail text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (producer, batch_id)
);

create table app.news_candidates (
  id uuid primary key default gen_random_uuid(),
  batch_id uuid references app.news_ingest_batches (id) on delete set null,
  source_id text references app.news_source_registry (id) on delete set null,
  external_id text,
  dedup_key text not null unique check (char_length(btrim(dedup_key)) > 0),
  canonical_url text not null check (canonical_url ~ '^https://'),
  title text not null check (char_length(btrim(title)) > 0),
  event_type text not null check (
    event_type in ('regulatory', 'guideline', 'trial', 'society', 'device', 'safety', 'clinical')
  ),
  published_at date,
  event_date date,
  effective_date date,
  primary_domain_hint text,
  secondary_domain_hints text[] not null default '{}',
  raw_metadata jsonb not null default '{}'::jsonb,
  verified_source_text text,
  status text not null default 'new' check (
    status in ('new', 'verified', 'selected', 'drafted', 'rejected', 'held', 'duplicate')
  ),
  rejection_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index news_candidates_status_idx on app.news_candidates (status, created_at desc);

create table app.news_events (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]*$'),
  dedup_key text not null unique check (char_length(btrim(dedup_key)) > 0),
  category text not null check (
    category in ('regulatory', 'guideline', 'trial', 'society', 'device', 'safety', 'clinical')
  ),
  geography text not null default 'global' check (geography in ('taiwan', 'us', 'eu', 'global')),
  evidence_status text not null check (
    evidence_status in ('approved', 'guideline', 'peer_reviewed', 'conference', 'preprint', 'registry', 'press_release')
  ),
  risk_tier text not null check (risk_tier in ('low', 'medium', 'high', 'reject')),
  status text not null default 'draft' check (
    status in ('draft', 'pending_review', 'published', 'rejected', 'withdrawn')
  ),
  review_status text not null default 'auto' check (review_status in ('auto', 'reviewed', 'revised')),
  event_date date,
  published_at date not null,
  effective_date date,
  current_revision_id uuid,
  first_published_at timestamptz,
  withdrawn_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index news_events_public_idx on app.news_events (published_at desc, id)
  where status = 'published' and withdrawn_at is null;

create table app.news_revisions (
  id uuid primary key default gen_random_uuid(),
  event_id text not null references app.news_events (id) on delete cascade,
  revision_number integer not null check (revision_number > 0),
  headline text not null check (char_length(btrim(headline)) > 0),
  what_happened text not null check (char_length(btrim(what_happened)) > 0),
  why_it_matters text not null check (char_length(btrim(why_it_matters)) > 0),
  clinical_relevance text not null check (char_length(btrim(clinical_relevance)) > 0),
  evidence_limitations text not null check (char_length(btrim(evidence_limitations)) > 0),
  correction_note text,
  model_name text,
  created_by text not null check (char_length(btrim(created_by)) > 0),
  created_at timestamptz not null default now(),
  unique (event_id, revision_number)
);

alter table app.news_events
  add constraint news_events_current_revision_fkey
  foreign key (current_revision_id) references app.news_revisions (id) deferrable initially deferred;

create table app.news_event_domains (
  event_id text not null references app.news_events (id) on delete cascade,
  domain_slug text not null references app.domains (slug),
  is_primary boolean not null default false,
  subtopic_id text references app.subtopics (id),
  taxonomy_version text not null check (char_length(btrim(taxonomy_version)) > 0),
  primary key (event_id, domain_slug)
);

-- Guarantees at most one primary domain per news event at the database level (ADR-0030/0031).
create unique index news_event_domains_one_primary on app.news_event_domains (event_id) where is_primary;
create index news_event_domains_domain_idx on app.news_event_domains (domain_slug, is_primary);

create table app.news_event_sources (
  id uuid primary key default gen_random_uuid(),
  event_id text not null references app.news_events (id) on delete cascade,
  source_id text references app.news_source_registry (id) on delete set null,
  url text not null check (url ~ '^https://'),
  title text not null check (char_length(btrim(title)) > 0),
  publisher text not null check (char_length(btrim(publisher)) > 0),
  source_kind text not null check (char_length(btrim(source_kind)) > 0),
  published_at date,
  fetched_at timestamptz not null default now(),
  unique (event_id, url)
);

create table app.news_claims (
  id uuid primary key default gen_random_uuid(),
  revision_id uuid not null references app.news_revisions (id) on delete cascade,
  claim_text text not null check (char_length(btrim(claim_text)) > 0),
  evidence_quote text not null check (char_length(btrim(evidence_quote)) > 0),
  source_url text not null check (source_url ~ '^https://'),
  verified boolean not null default false,
  created_at timestamptz not null default now()
);

create index news_claims_revision_idx on app.news_claims (revision_id);

create table app.news_review_actions (
  id uuid primary key default gen_random_uuid(),
  event_id text not null references app.news_events (id) on delete cascade,
  revision_id uuid references app.news_revisions (id) on delete set null,
  actor_id uuid references app.accounts (id) on delete set null,
  actor_label text not null check (char_length(btrim(actor_label)) > 0),
  action text not null check (action in ('approve', 'reject', 'withdraw', 'revise', 'hold')),
  reason text not null check (char_length(btrim(reason)) > 0),
  created_at timestamptz not null default now()
);

create index news_review_actions_event_idx on app.news_review_actions (event_id, created_at desc);

create table app.news_runs (
  id uuid primary key default gen_random_uuid(),
  stage text not null check (stage in ('intake', 'collect', 'select', 'draft', 'gate', 'publish')),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null check (status in ('running', 'ok', 'partial', 'failed', 'budget_stopped', 'disabled')),
  candidates_processed integer not null default 0 check (candidates_processed >= 0),
  drafts_created integer not null default 0 check (drafts_created >= 0),
  estimated_cost_usd numeric(10, 4) not null default 0 check (estimated_cost_usd >= 0),
  summary jsonb not null default '{}'::jsonb,
  error_detail text
);

-- Public read-only view: ONLY published, non-withdrawn events joined to their active revision.
-- Never exposes drafts, pending/rejected/withdrawn events, internal scores, or review notes.
create view app.public_news_events as
select
  e.id,
  e.category,
  e.geography,
  e.evidence_status,
  e.review_status,
  e.event_date,
  e.published_at,
  e.effective_date,
  e.first_published_at,
  e.updated_at,
  r.revision_number,
  r.headline,
  r.what_happened,
  r.why_it_matters,
  r.clinical_relevance,
  r.evidence_limitations,
  r.correction_note,
  (
    select ed.domain_slug
    from app.news_event_domains ed
    where ed.event_id = e.id and ed.is_primary = true
    limit 1
  ) as primary_domain,
  coalesce(
    (
      select array_agg(ed.domain_slug order by d.sort_order, ed.domain_slug)
      from app.news_event_domains ed
      join app.domains d on d.slug = ed.domain_slug
      where ed.event_id = e.id and ed.is_primary = false
    ),
    '{}'::text[]
  ) as secondary_domains,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'url', s.url,
          'title', s.title,
          'publisher', s.publisher,
          'sourceKind', s.source_kind,
          'publishedAt', s.published_at
        )
        order by s.published_at desc nulls last, s.url
      )
      from app.news_event_sources s
      where s.event_id = e.id
    ),
    '[]'::jsonb
  ) as sources
from app.news_events e
join app.news_revisions r on r.id = e.current_revision_id
where e.status = 'published'
  and e.withdrawn_at is null;

-- Public source health view: allows distinguishing "no new events today" vs "some sources delayed"
-- without exposing internal error tracebacks or source credentials/config.
create view app.public_news_source_health as
select
  id,
  name,
  source_type,
  enabled,
  last_success_at,
  last_error_at,
  (last_error_at is not null and (last_success_at is null or last_error_at > last_success_at)) as degraded
from app.news_source_registry
where enabled = true;

-- Privileges and RLS: strict isolation per ADR-0016 / ADR-0021 / ADR-0031.
-- guthub_api may ONLY read the two public views; all draft/internal tables stay inaccessible to guthub_api.
revoke all on
  app.news_source_registry,
  app.news_ingest_batches,
  app.news_candidates,
  app.news_events,
  app.news_revisions,
  app.news_event_domains,
  app.news_event_sources,
  app.news_claims,
  app.news_review_actions,
  app.news_runs,
  app.public_news_events,
  app.public_news_source_health
  from public, anon, authenticated, service_role, guthub_api;

grant select on app.public_news_events, app.public_news_source_health to guthub_api;

do $$
declare t text;
begin
  foreach t in array array[
    'news_source_registry',
    'news_ingest_batches',
    'news_candidates',
    'news_events',
    'news_revisions',
    'news_event_domains',
    'news_event_sources',
    'news_claims',
    'news_review_actions',
    'news_runs'
  ] loop
    execute format('alter table app.%I enable row level security', t);
  end loop;
end $$;
