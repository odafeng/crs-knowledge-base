-- C5 #95: Web Push for new stories. A subscription is what a browser hands out when a reader turns push on: a URL at
-- the browser vendor's push service and two keys. It names a browser, not a person, and is not linked to an account
-- (privacy policy). Browsers reach the table only through the API; the Data API is not exposed (ADR-0020).
create table app.push_subscriptions (
  endpoint text primary key
    check (length(endpoint) <= 2048)
    -- The sender posts to this URL, so it must be one of the push services browsers actually use.
    check (endpoint ~ '^https://([a-z0-9-]+\.)*(googleapis\.com|mozilla\.com|push\.apple\.com|windows\.com)/'),
  p256dh text not null check (p256dh ~ '^[A-Za-z0-9_-]{80,100}$'),
  auth text not null check (auth ~ '^[A-Za-z0-9_-]{16,32}$'),
  created_at timestamptz not null default now()
);

alter table app.push_subscriptions enable row level security;
revoke all on app.push_subscriptions from public, anon, authenticated, service_role;
grant select, insert, update, delete on app.push_subscriptions to guthub_api;
create policy guthub_api_access on app.push_subscriptions to guthub_api using (true) with check (true);

-- One row per story ever announced. The sender claims the row before sending, so a story is pushed at most once,
-- however often the job, a page rebuild or a deploy runs; the counts are filled in afterwards.
create table app.push_announcements (
  news_id text primary key references app.news (id),
  claimed_at timestamptz not null default now(),
  sent integer check (sent >= 0),
  removed integer check (removed >= 0),
  failed integer check (failed >= 0)
);

alter table app.push_announcements enable row level security;
revoke all on app.push_announcements from public, anon, authenticated, service_role;
grant select, insert, update on app.push_announcements to guthub_api;
create policy guthub_api_access on app.push_announcements to guthub_api using (true) with check (true);

-- Stories published before push existed are not news to anyone: mark them announced, sending nothing.
insert into app.push_announcements (news_id, sent, removed, failed) select id, 0, 0, 0 from app.news;
