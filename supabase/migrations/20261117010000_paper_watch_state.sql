-- E3 #76: Paper Watch's tracking state (which DOIs and conference abstracts were already processed) moves with the
-- content to PostgreSQL at cutover, since a Cloud Run job has no persistent disk. One JSON document per name, read
-- and written whole, exactly like data/tracked-dois.json and data/tracked-abstracts.json. Only the content writer
-- (owner role) uses it; no grants to client roles or guthub_api.
create table app.paper_watch_state (
  name text primary key check (name in ('tracked-dois', 'tracked-abstracts')),
  data jsonb not null check (jsonb_typeof(data) = 'object'),
  updated_at timestamptz not null default now()
);
alter table app.paper_watch_state enable row level security;
revoke all on app.paper_watch_state from public, anon, authenticated, service_role;
