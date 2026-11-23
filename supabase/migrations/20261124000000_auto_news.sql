-- K2 #252: scripts/news_writer.py writes auto-generated news stories through the content writer.
alter table app.publish_events drop constraint publish_events_action_check;
alter table app.publish_events add constraint publish_events_action_check
  check (action in ('publish_paper', 'publish_commentary', 'publish_news', 'unpublish', 'review', 'summarize'));
