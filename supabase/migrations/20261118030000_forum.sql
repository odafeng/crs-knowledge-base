-- H6 #128: the colorectal surgeon forum (ADR-0022). Only verified members read or write it; the API checks membership
-- on every request. Threads and replies share one table: a post without thread_id opens a thread and alone carries the
-- title and the optional link to a topic or paper. The rules are those of reader comments (ADR-0017): signed or
-- anonymous to other members, a private author mapping, the first post of an account waits for moderation, soft
-- delete, and the mapping cleared 90 days after deletion.

create table app.forum_posts (
  id uuid primary key default gen_random_uuid(),
  -- The opening post of the thread; null for the opening post itself. The API only ever points this at an opener.
  thread_id uuid references app.forum_posts (id),
  title text check (char_length(btrim(title)) between 1 and 500),
  topic_key text references app.topics (key),
  paper_id text references app.papers (id),
  -- Private author mapping: never selected by app.visible_forum_posts. Nulled 90 days after deletion.
  author_id uuid references app.accounts (id) on delete set null,
  -- Hard ceiling only; the policy limit is enforced and tunable in the API.
  body text not null check (char_length(btrim(body)) between 1 and 20000),
  anonymous boolean not null,
  display_name text check (display_name <> ''),
  status app.comment_status not null default 'pending',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  check (anonymous = (display_name is null)),
  check (author_id is not null or deleted_at is not null),
  check ((thread_id is null) = (title is not null)),
  check (thread_id is null or (topic_key is null and paper_id is null))
);
create index forum_posts_threads_idx on app.forum_posts (created_at, id) where thread_id is null and deleted_at is null;
create index forum_posts_replies_idx on app.forum_posts (thread_id, created_at, id) where deleted_at is null;
create index forum_posts_author_idx on app.forum_posts (author_id, created_at);

create table app.forum_post_likes (
  post_id uuid not null references app.forum_posts (id) on delete cascade,
  account_id uuid not null references app.accounts (id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (post_id, account_id)
);

create table app.forum_reports (
  id uuid primary key default gen_random_uuid(),
  post_id uuid not null references app.forum_posts (id),
  reporter_id uuid references app.accounts (id) on delete set null,
  reason text not null check (char_length(btrim(reason)) between 1 and 1000),
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  unique (post_id, reporter_id)
);

-- Append-only audit of forum moderation. actor_id has no FK so the record survives account purges.
create table app.forum_moderation_events (
  id bigint generated always as identity primary key,
  post_id uuid not null references app.forum_posts (id),
  actor_id uuid not null,
  action app.moderation_action not null,
  reason text not null check (btrim(reason) <> ''),
  created_at timestamptz not null default now()
);

-- The first post of an account waits for moderation unless the maintainer has already approved something it wrote,
-- here or as a paper comment. The caller's status is ignored so the API cannot skip the rule by accident.
create function app.set_initial_forum_post_status() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.status := case
    when exists (select 1 from app.forum_posts p where p.author_id = new.author_id and p.status = 'published')
      or exists (select 1 from app.comments c where c.author_id = new.author_id and c.status = 'published')
    then 'published'::app.comment_status
    else 'pending'::app.comment_status
  end;
  return new;
end $$;

create trigger forum_posts_initial_status
before insert on app.forum_posts
for each row execute function app.set_initial_forum_post_status();

-- Removing an account soft-deletes its forum posts too, for the same reason as its comments.
create or replace function app.soft_delete_account_comments() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  update app.comments set deleted_at = now() where author_id = old.id and deleted_at is null;
  update app.forum_posts set deleted_at = now() where author_id = old.id and deleted_at is null;
  return old;
end $$;

create or replace function app.purge_deleted_authors() returns void
language sql security definer set search_path = '' as $$
  update app.comments set author_id = null
  where author_id is not null and deleted_at < now() - interval '90 days';
  update app.forum_posts set author_id = null
  where author_id is not null and deleted_at < now() - interval '90 days';
  delete from app.accounts where deleted_at < now() - interval '90 days';
$$;

-- What members see: published, not deleted, and (for replies) in a thread that is itself visible. No author column.
create view app.visible_forum_posts with (security_invoker = true) as
  select p.id, p.thread_id, p.title, p.topic_key, p.paper_id, p.body, p.anonymous, p.display_name, p.created_at,
         p.updated_at
  from app.forum_posts p left join app.forum_posts t on t.id = p.thread_id
  where p.status = 'published' and p.deleted_at is null
    and (p.thread_id is null or (t.status = 'published' and t.deleted_at is null));

alter table app.forum_posts enable row level security;
alter table app.forum_post_likes enable row level security;
alter table app.forum_reports enable row level security;
alter table app.forum_moderation_events enable row level security;
revoke all on app.forum_posts, app.forum_post_likes, app.forum_reports, app.forum_moderation_events,
  app.visible_forum_posts from public, anon, authenticated, service_role;
revoke all on function app.set_initial_forum_post_status() from public, anon, authenticated, service_role;
grant select, insert, update on app.forum_posts to guthub_api;
grant select on app.visible_forum_posts to guthub_api;
grant select, insert, delete on app.forum_post_likes to guthub_api;
grant select, insert on app.forum_reports to guthub_api;
grant update (resolved_at) on app.forum_reports to guthub_api;
grant select, insert on app.forum_moderation_events to guthub_api;
create policy guthub_api_access on app.forum_posts to guthub_api using (true) with check (true);
create policy guthub_api_access on app.forum_post_likes to guthub_api using (true) with check (true);
create policy guthub_api_access on app.forum_reports to guthub_api using (true) with check (true);
create policy guthub_api_access on app.forum_moderation_events to guthub_api using (true) with check (true);
