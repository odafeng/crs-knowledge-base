-- H3 #125: search queries per day (Asia/Taipei), so one actor rotating addresses can exhaust at most a day's share
-- of the month's query budget. The day's tokens are also counted in app.embedding_usage; this table only caps.

create table app.query_usage (
  day date primary key,
  tokens bigint not null default 0 check (tokens >= 0)
);

alter table app.query_usage enable row level security;
revoke all on app.query_usage from public, anon, authenticated, service_role;
grant select, insert, update on app.query_usage to guthub_api;
create policy guthub_api_access on app.query_usage to guthub_api using (true) with check (true);
