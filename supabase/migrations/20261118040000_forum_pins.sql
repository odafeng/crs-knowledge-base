-- H7 #129: the maintainer pins threads to the top of the forum (ADR-0022). Only an opening post can be pinned, and
-- pinning and unpinning are audited like every other moderation action.
alter type app.moderation_action add value 'pin';
alter type app.moderation_action add value 'unpin';

alter table app.forum_posts add column pinned_at timestamptz,
  add constraint forum_posts_pin_opens_thread check (pinned_at is null or thread_id is null);

-- Same view, plus whether a thread is pinned. Still no author column.
create or replace view app.visible_forum_posts with (security_invoker = true) as
  select p.id, p.thread_id, p.title, p.topic_key, p.paper_id, p.body, p.anonymous, p.display_name, p.created_at,
         p.updated_at, p.pinned_at
  from app.forum_posts p left join app.forum_posts t on t.id = p.thread_id
  where p.status = 'published' and p.deleted_at is null
    and (p.thread_id is null or (t.status = 'published' and t.deleted_at is null));
