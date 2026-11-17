-- G6 #117: topics a signed-in reader follows. Private to the reader: only the API reads it, for that reader alone
-- (GET /me/topics); pages never contain it, so no shared cache holds it. Deleted with the account.
create table app.topic_subscriptions (
  account_id uuid not null references app.accounts (id) on delete cascade,
  topic_key text not null references app.topics (key) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (account_id, topic_key)
);

alter table app.topic_subscriptions enable row level security;
revoke all on app.topic_subscriptions from public, anon, authenticated, service_role;
grant select, insert, delete on app.topic_subscriptions to guthub_api;
create policy guthub_api_access on app.topic_subscriptions to guthub_api using (true) with check (true);
