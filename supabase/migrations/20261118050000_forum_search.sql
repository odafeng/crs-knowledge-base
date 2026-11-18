-- H8 #130: forum posts in natural-language search (ADR-0022). scripts/search_index.py embeds each published thread
-- opener and reply (thread title and body, never the author); the API returns them only to verified members and checks
-- app.visible_forum_posts on every query, so a hidden or deleted post leaves the results at once.
alter table app.search_chunks drop constraint search_chunks_kind_check,
  add constraint search_chunks_kind_check check (kind in ('paper', 'news', 'card', 'forum'));
