-- H1 #123: readers like comments. One like per account and comment; who liked what stays private (the API returns
-- counts, and each reader only their own likes). Likes go with the account when it is purged.
create table app.comment_likes (
  comment_id uuid not null references app.comments (id) on delete cascade,
  account_id uuid not null references app.accounts (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (comment_id, account_id)
);
create index comment_likes_account_idx on app.comment_likes (account_id, created_at);

alter table app.comment_likes enable row level security;
revoke all on app.comment_likes from public, anon, authenticated, service_role;
grant select, insert, delete on app.comment_likes to guthub_api;
create policy guthub_api_access on app.comment_likes to guthub_api using (true) with check (true);
