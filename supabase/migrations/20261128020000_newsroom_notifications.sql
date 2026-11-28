-- N7 #292 (ADR-0031): Idempotent Web Push announcement log for published Newsroom events.
-- Kept separate from legacy app.push_announcements (which FKs to app.news) so both systems
-- enforce foreign-key integrity and at-most-once delivery independently.

create table app.news_event_push_announcements (
  event_id text primary key references app.news_events (id) on delete cascade,
  claimed_at timestamptz not null default now(),
  sent integer check (sent >= 0),
  removed integer check (removed >= 0),
  failed integer check (failed >= 0)
);

alter table app.news_event_push_announcements enable row level security;
revoke all on app.news_event_push_announcements from public, anon, authenticated, service_role, guthub_api;
grant select, insert, update on app.news_event_push_announcements to guthub_api;
create policy guthub_api_access on app.news_event_push_announcements to guthub_api using (true) with check (true);
