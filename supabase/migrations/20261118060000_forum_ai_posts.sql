-- H9 #161: the first forum threads are opened by the site's AI (ADR-0022). An AI post belongs to no account: it is
-- signed "GutHub AI", marked `ai`, and published at once because the maintainer reviewed its draft before
-- scripts/forum_ai_topics.py inserted it as the content owner. The API cannot mark a post as AI: guthub_api loses its
-- table-wide insert and update on forum_posts and keeps only the columns it writes.

alter table app.forum_posts add column ai boolean not null default false,
  drop constraint forum_posts_check1,
  add constraint forum_posts_author_or_ai check (author_id is not null or deleted_at is not null or ai),
  add constraint forum_posts_ai_signed check (not ai or (author_id is null and not anonymous));

revoke insert, update on app.forum_posts from guthub_api;
grant insert (thread_id, title, topic_key, paper_id, author_id, body, anonymous, display_name)
  on app.forum_posts to guthub_api;
grant update (body, title, updated_at, deleted_at, status, pinned_at) on app.forum_posts to guthub_api;

create or replace function app.set_initial_forum_post_status() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.status := case
    when new.ai then 'published'::app.comment_status
    when exists (select 1 from app.forum_posts p where p.author_id = new.author_id and p.status = 'published')
      or exists (select 1 from app.comments c where c.author_id = new.author_id and c.status = 'published')
    then 'published'::app.comment_status
    else 'pending'::app.comment_status
  end;
  return new;
end $$;

-- Same view, plus the AI mark. Still no author column.
create or replace view app.visible_forum_posts with (security_invoker = true) as
  select p.id, p.thread_id, p.title, p.topic_key, p.paper_id, p.body, p.anonymous, p.display_name, p.created_at,
         p.updated_at, p.pinned_at, p.ai
  from app.forum_posts p left join app.forum_posts t on t.id = p.thread_id
  where p.status = 'published' and p.deleted_at is null
    and (p.thread_id is null or (t.status = 'published' and t.deleted_at is null));
