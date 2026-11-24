-- K6 (#256): Store raw plain text in text columns (decoding legacy HTML entities) and normalize legacy stored HTML
-- attributes/tags so the read API and web frontend no longer repeat per-request sanitization or entity decoding.

create or replace function app._k6_unescape_text(val text) returns text
language sql immutable set search_path = '' as $$
  select case
    when val is null then null
    else replace(
      replace(
        replace(
          replace(
            replace(
              replace(val, '&lt;', '<'),
              '&gt;', '>'
            ),
            '&quot;', '"'
          ),
          '&#39;', ''''
        ),
        '&#x27;', ''''
      ),
      '&amp;', '&'
    )
  end;
$$;

create or replace function app._k6_clean_html(val text) returns text
language sql immutable set search_path = '' as $$
  select case
    when val is null then null
    else regexp_replace(
      regexp_replace(
        regexp_replace(
          regexp_replace(
            regexp_replace(val, '<th>[[:space:]]*</th>', '<td></td>', 'gi'),
            '<a[[:space:]][^>]*href="docs/[^"]*"[^>]*>(.*?)</a>', '\1', 'gi'
          ),
          '[[:space:]]+(target|rel|style)="[^"]*"', '', 'gi'
        ),
        '</?(details|summary)([^>]*)>', '', 'gi'
      ),
      '(<a[[:space:]][^>]*)(>)', '\1 rel="noopener noreferrer"\2', 'gi'
    )
  end;
$$;

-- 1. Decode plain-text fields and clean stored detail_html on app.papers (also refreshes search_text via trigger).
update app.papers
set
  journal = app._k6_unescape_text(journal),
  regimen = app._k6_unescape_text(regimen),
  endpoint = app._k6_unescape_text(endpoint),
  result = app._k6_unescape_text(result),
  bottom_line = app._k6_unescape_text(bottom_line),
  n = case
    when jsonb_typeof(n) = 'string' then to_jsonb(app._k6_unescape_text(n #>> '{}'))
    else n
  end,
  detail_html = app._k6_clean_html(detail_html);

-- 2. Decode plain-text fields on app.research_commentary.
update app.research_commentary
set
  title = app._k6_unescape_text(title),
  journal = app._k6_unescape_text(journal),
  summary = app._k6_unescape_text(summary);

-- 3. Clean stored card HTML on app.topics (standard_of_care & robotic_sections).
update app.topics
set standard_of_care = coalesce(
  (
    select jsonb_agg(
      jsonb_set(card, '{body_html}', to_jsonb(app._k6_clean_html(card->>'body_html')))
    )
    from jsonb_array_elements(standard_of_care) as card
  ),
  '[]'::jsonb
)
where jsonb_array_length(standard_of_care) > 0;

update app.topics
set robotic_sections = coalesce(
  (
    select jsonb_agg(
      jsonb_set(
        jsonb_set(
          jsonb_set(
            sec,
            '{timeline}',
            coalesce(
              (
                select jsonb_agg(jsonb_set(item, '{finding}', to_jsonb(app._k6_clean_html(item->>'finding'))))
                from jsonb_array_elements(sec->'timeline') as item
              ),
              '[]'::jsonb
            )
          ),
          '{cards}',
          coalesce(
            (
              select jsonb_agg(jsonb_set(card, '{body}', to_jsonb(app._k6_clean_html(card->>'body'))))
              from jsonb_array_elements(sec->'cards') as card
            ),
            '[]'::jsonb
          )
        ),
        '{detailHtml}',
        coalesce(
          (
            select jsonb_agg(to_jsonb(app._k6_clean_html(h)))
            from jsonb_array_elements_text(sec->'detailHtml') as h
          ),
          '[]'::jsonb
        )
      )
    )
    from jsonb_array_elements(robotic_sections) as sec
  ),
  '[]'::jsonb
)
where jsonb_array_length(robotic_sections) > 0;

drop function app._k6_clean_html(text);
drop function app._k6_unescape_text(text);
