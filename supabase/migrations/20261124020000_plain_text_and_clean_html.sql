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
language plpgsql immutable set search_path = '' as $$
declare
  s text;
  out text := '';
  pos int := 1;
  len int;
  lt int;
  gt int;
  tag_raw text;
  is_close boolean;
  tag_name text;
  attrs text;
  m text[];
  href_val text;
  cls_val text;
  cs_val text;
  rs_val text;
  rebuilt text;
begin
  if val is null then
    return null;
  end if;
  -- Strip executable/embedded block elements along with their content.
  s := regexp_replace(
    val,
    '<(script|style|iframe|object|embed|svg|math)([[:space:]][^>]*)?>.*?</\1[[:space:]]*>',
    '',
    'gi'
  );
  -- Apply legacy sitegen repairs before allowlist filtering.
  s := regexp_replace(s, '<th>[[:space:]]*</th>', '<td></td>', 'gi');
  s := regexp_replace(s, '<a[[:space:]][^>]*href="docs/[^"]*"[^>]*>(.*?)</a>', '\1', 'gi');

  len := length(s);
  while pos <= len loop
    lt := strpos(substr(s, pos), '<');
    if lt = 0 then
      out := out || substr(s, pos);
      exit;
    end if;
    out := out || substr(s, pos, lt - 1);
    pos := pos + lt - 1;
    -- Bare '<' not starting a tag or comment (e.g. "p<0.05</p>") is plain text.
    if pos = len or substr(s, pos + 1, 1) !~ '^[A-Za-z/!]' then
      out := out || '&lt;';
      pos := pos + 1;
      continue;
    end if;
    gt := strpos(substr(s, pos), '>');
    if gt = 0 then
      out := out || '&lt;' || substr(s, pos + 1);
      exit;
    end if;
    tag_raw := substr(s, pos + 1, gt - 2);
    pos := pos + gt;

    m := regexp_match(tag_raw, '^[[:space:]]*(/?)[[:space:]]*([A-Za-z][A-Za-z0-9]*)([[:space:]].*)?$');
    if m is null then
      continue;
    end if;
    is_close := (m[1] = '/');
    tag_name := lower(m[2]);
    attrs := coalesce(m[3], '');

    if tag_name not in (
      'a', 'br', 'div', 'em', 'h3', 'li', 'ol', 'p', 's', 'strong',
      'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul'
    ) then
      continue;
    end if;

    if is_close then
      if tag_name <> 'br' then
        out := out || '</' || tag_name || '>';
      end if;
      continue;
    end if;

    rebuilt := '<' || tag_name;
    if tag_name = 'a' then
      href_val := coalesce(
        (regexp_match(attrs, '(?:^|[[:space:]])href[[:space:]]*=[[:space:]]*"([^"]*)"', 'i'))[1],
        (regexp_match(attrs, '(?:^|[[:space:]])href[[:space:]]*=[[:space:]]*''([^'']*)''', 'i'))[1]
      );
      if href_val is not null and href_val ~* '^[[:space:]]*(https?://|mailto:|/[^/]|#)' then
        rebuilt := rebuilt || ' href="' || replace(trim(href_val), '"', '&quot;') || '"';
      end if;
      rebuilt := rebuilt || ' rel="noopener noreferrer"';
    elsif tag_name in ('div', 'p') then
      cls_val := coalesce(
        (regexp_match(attrs, '(?:^|[[:space:]])class[[:space:]]*=[[:space:]]*"([^"]*)"', 'i'))[1],
        (regexp_match(attrs, '(?:^|[[:space:]])class[[:space:]]*=[[:space:]]*''([^'']*)''', 'i'))[1]
      );
      if cls_val is not null then
        rebuilt := rebuilt || ' class="' || replace(cls_val, '"', '&quot;') || '"';
      end if;
    elsif tag_name in ('td', 'th') then
      cs_val := (regexp_match(attrs, '(?:^|[[:space:]])colspan[[:space:]]*=[[:space:]]*"?([0-9]+)"?', 'i'))[1];
      rs_val := (regexp_match(attrs, '(?:^|[[:space:]])rowspan[[:space:]]*=[[:space:]]*"?([0-9]+)"?', 'i'))[1];
      if cs_val is not null then
        rebuilt := rebuilt || ' colspan="' || cs_val || '"';
      end if;
      if rs_val is not null then
        rebuilt := rebuilt || ' rowspan="' || rs_val || '"';
      end if;
    end if;
    out := out || rebuilt || '>';
  end loop;
  return out;
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
