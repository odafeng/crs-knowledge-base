-- E2 #73: one authority writes content at a time, and publish/unpublish retries are recorded so they do not repeat.
-- Neither table is exposed: no grants to client roles or guthub_api; the content writer connects as the owner role,
-- like the importer.

-- Which side accepts content writes: 'json' (data/*.json in git, the default until cutover) or 'postgres'. The
-- importer only runs while this says 'json'; the database writer only while it says 'postgres'.
create table app.content_writer (
  id boolean primary key default true check (id),
  writer text not null check (writer in ('json', 'postgres')),
  -- Manifest of the JSON the database was verified against when it took over (import_content.manifest).
  watermark jsonb check (watermark is null or jsonb_typeof(watermark) = 'object'),
  changed_at timestamptz not null default now()
);
insert into app.content_writer (writer) values ('json');

-- One row per applied publish, accept or unpublish request. The key names the request (action, target and workflow
-- run), so a retried run finds its row and stops instead of writing twice.
create table app.publish_events (
  key text primary key check (btrim(key) <> ''),
  action text not null check (action in ('publish_paper', 'publish_commentary', 'unpublish')),
  summary text not null,
  created_at timestamptz not null default now()
);

alter table app.content_writer enable row level security;
alter table app.publish_events enable row level security;
revoke all on app.content_writer, app.publish_events from public, anon, authenticated, service_role;
