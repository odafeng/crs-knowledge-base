-- N5 #290 (ADR-0031): Extend app.content_requests and app.publish_events for Newsroom events,
-- and provide an admin-only read view (app.admin_news_review_queue) while preserving ADR-0021
-- (guthub_api still holds zero write privileges on any content table).

alter table app.content_requests
  add column payload jsonb not null default '{}'::jsonb;

alter table app.content_requests drop constraint content_requests_action_check;
alter table app.content_requests add constraint content_requests_action_check
  check (action in ('review', 'unpublish', 'approve', 'reject', 'withdraw', 'revise'));

alter table app.content_requests drop constraint content_requests_kind_check;
alter table app.content_requests add constraint content_requests_kind_check
  check (kind in ('paper', 'news', 'news_event'));

grant insert (action, kind, target, requested_by, payload) on app.content_requests to guthub_api;

alter table app.publish_events drop constraint publish_events_action_check;
alter table app.publish_events add constraint publish_events_action_check
  check (action in (
    'publish_paper', 'publish_commentary', 'unpublish', 'review',
    'news_approve', 'news_reject', 'news_withdraw', 'news_revise', 'news_auto_publish'
  ));

-- Admin review queue view (read exclusively by FastAPI after require_admin):
-- exposes event metadata, current revision, sources, claims, and recent audit actions
-- without granting guthub_api direct table privileges on app.news_events or draft tables.
create view app.admin_news_review_queue as
select
  e.id,
  e.category,
  e.geography,
  e.evidence_status,
  e.risk_tier,
  e.status,
  e.review_status,
  e.event_date,
  e.published_at,
  e.effective_date,
  e.created_at,
  e.updated_at,
  r.id as revision_id,
  r.revision_number,
  r.headline,
  r.what_happened,
  r.why_it_matters,
  r.clinical_relevance,
  r.evidence_limitations,
  r.correction_note,
  (
    select ed.domain_slug
    from app.news_event_domains ed
    where ed.event_id = e.id and ed.is_primary = true
    limit 1
  ) as primary_domain,
  coalesce(
    (
      select array_agg(ed.domain_slug order by d.sort_order, ed.domain_slug)
      from app.news_event_domains ed
      join app.domains d on d.slug = ed.domain_slug
      where ed.event_id = e.id and ed.is_primary = false
    ),
    '{}'::text[]
  ) as secondary_domains,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'url', s.url,
          'title', s.title,
          'publisher', s.publisher,
          'sourceKind', s.source_kind,
          'publishedAt', s.published_at
        )
        order by s.published_at desc nulls last, s.url
      )
      from app.news_event_sources s
      where s.event_id = e.id
    ),
    '[]'::jsonb
  ) as sources,
  coalesce(
    (
      select jsonb_agg(
        jsonb_build_object(
          'claimText', c.claim_text,
          'evidenceQuote', c.evidence_quote,
          'sourceUrl', c.source_url,
          'verified', c.verified
        )
        order by c.created_at, c.id
      )
      from app.news_claims c
      where c.revision_id = r.id
    ),
    '[]'::jsonb
  ) as claims
from app.news_events e
join app.news_revisions r on r.id = e.current_revision_id;

revoke all on app.admin_news_review_queue from public, anon, authenticated, service_role, guthub_api;
grant select on app.admin_news_review_queue to guthub_api;
