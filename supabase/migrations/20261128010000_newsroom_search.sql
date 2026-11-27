-- N6 #291 (ADR-0031): Allow published Newsroom events (kind = 'news_event') in semantic search chunks.
-- No new tables or views; app.public_news_events continues to gate all public reads.

alter table app.search_chunks drop constraint search_chunks_kind_check;
alter table app.search_chunks add constraint search_chunks_kind_check
  check (kind in ('paper', 'news', 'news_event', 'card', 'forum'));
