-- E6 #159: an admin marks an auto-published paper or story as reviewed, or takes it down, from the site.
-- The API may not write content (ADR-0021: one writer), so it only records the request here and starts the
-- content-requests job, which applies it through the content writer and fills in done_at and result.
create table app.content_requests (
  id bigint generated always as identity primary key,
  action text not null check (action in ('review', 'unpublish')),
  kind text not null check (kind in ('paper', 'news')),
  target text not null check (char_length(btrim(target)) between 1 and 200),
  -- Kept when the admin's account is deleted: the request is part of the content's history.
  requested_by uuid references app.accounts (id) on delete set null,
  requested_at timestamptz not null default now(),
  done_at timestamptz,
  ok boolean,
  result text,
  check ((done_at is null) = (ok is null))
);
create index content_requests_pending on app.content_requests (id) where done_at is null;

alter table app.content_requests enable row level security;
revoke all on app.content_requests from public, anon, authenticated, service_role;
grant select, insert (action, kind, target, requested_by) on app.content_requests to guthub_api;
create policy guthub_api_access on app.content_requests to guthub_api using (true) with check (true);

alter table app.publish_events drop constraint publish_events_action_check;
alter table app.publish_events add constraint publish_events_action_check
  check (action in ('publish_paper', 'publish_commentary', 'unpublish', 'review'));
