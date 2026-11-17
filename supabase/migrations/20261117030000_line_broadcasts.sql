-- G3 #114: one LINE broadcast per day at most. The job claims the day with a retry key before sending and reuses
-- that key on every retry, so LINE itself refuses a second delivery (X-Line-Retry-Key) even if the job died after
-- LINE accepted the message but before sent_at was recorded.
create table app.line_broadcasts (
  day date primary key,
  retry_key uuid not null,
  url text not null,
  claimed_at timestamptz not null default now(),
  sent_at timestamptz
);

alter table app.line_broadcasts enable row level security;
revoke all on app.line_broadcasts from public, anon, authenticated, service_role;
grant select, insert, update on app.line_broadcasts to guthub_api;
create policy guthub_api_access on app.line_broadcasts to guthub_api using (true) with check (true);
