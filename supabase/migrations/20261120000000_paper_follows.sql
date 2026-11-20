-- G8 #119 (ADR-0022, 2026-11-20): readers follow papers and get one email a day listing how many new comments each
-- followed paper has. Commenting on a paper follows it; either can be undone.

-- When a comment became visible. A first comment waits for moderation and may be published days after it was
-- written, so the digest counts by this time, not created_at. Set whenever the status turns to published.
alter table app.comments add column published_at timestamptz;
update app.comments set published_at = created_at where status = 'published';

create function app.set_comment_published_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.status = 'published' and (tg_op = 'INSERT' or old.status is distinct from 'published') then
    new.published_at := now();
  end if;
  return new;
end $$;

-- Named to run after comments_initial_status, which decides the status on insert (triggers fire in name order).
create trigger comments_x_published_at
before insert or update of status on app.comments
for each row execute function app.set_comment_published_at();

create table app.paper_follows (
  account_id uuid not null references app.accounts (id) on delete cascade,
  paper_id text not null references app.papers (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (account_id, paper_id)
);
create index paper_follows_paper_idx on app.paper_follows (paper_id);

alter table app.paper_follows enable row level security;
revoke all on app.paper_follows from public, anon, authenticated, service_role;
grant select, insert, delete on app.paper_follows to guthub_api;
create policy guthub_api_access on app.paper_follows to guthub_api using (true) with check (true);

-- The digest can be turned off without unfollowing anything. The token goes into every digest's unsubscribe links,
-- so a reader can stop the mail without signing in; it says nothing about the account and can be rotated.
alter table app.accounts
  add column comment_digest boolean not null default true,
  add column digest_token uuid not null default gen_random_uuid() unique;

-- One row per account and day, claimed before sending; the id is the Resend idempotency key, so a rerun after the
-- mail went out but before sent_at was recorded does not send it twice.
create table app.comment_digests (
  account_id uuid not null references app.accounts (id) on delete cascade,
  day date not null,
  idempotency_key uuid not null default gen_random_uuid(),
  claimed_at timestamptz not null default now(),
  sent_at timestamptz,
  primary key (account_id, day)
);

alter table app.comment_digests enable row level security;
revoke all on app.comment_digests from public, anon, authenticated, service_role;
grant select, insert, update on app.comment_digests to guthub_api;
create policy guthub_api_access on app.comment_digests to guthub_api using (true) with check (true);

-- The day's digest: for each follower with the digest on, each followed paper with comments published in
-- [since, until) by someone else, and how many. Emails live only in auth.users, which guthub_api cannot read; this
-- function hands out the address of exactly these readers and nothing else, hence security definer. Comment authors
-- are never returned, signed or not.
create function app.comment_digest(since timestamptz, until timestamptz)
returns table (account_id uuid, email text, digest_token uuid, paper_id text, new_comments bigint)
language sql stable security definer set search_path = '' as $$
  select f.account_id, u.email::text, a.digest_token, f.paper_id, count(*)
  from app.paper_follows f
  join app.accounts a on a.id = f.account_id and a.deleted_at is null and a.comment_digest
  join auth.users u on u.id = f.account_id and u.email is not null
  join app.papers p on p.id = f.paper_id and p.withdrawn_at is null
  join app.comments c on c.paper_id = f.paper_id
    and c.status = 'published' and c.deleted_at is null
    and c.published_at >= since and c.published_at < until
    and c.author_id is distinct from f.account_id
  group by f.account_id, u.email, a.digest_token, f.paper_id
$$;

revoke all on function app.comment_digest(timestamptz, timestamptz) from public, anon, authenticated, service_role;
grant execute on function app.comment_digest(timestamptz, timestamptz) to guthub_api;
