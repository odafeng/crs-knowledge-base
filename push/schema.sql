-- Push subscriptions. Run once in the project's SQL editor (Supabase) or with psql.
--
-- A row is what the browser hands out when a reader turns push on: a URL at the browser vendor's push
-- service plus two keys. It names a browser, not a person. Nothing else is stored.

create table if not exists public.push_subscriptions (
  endpoint   text primary key
             check (length(endpoint) <= 2048)
             -- Only the push services browsers actually use: the sender posts to this URL, so it must not be arbitrary.
             check (endpoint ~ '^https://([a-z0-9-]+\.)*(googleapis\.com|mozilla\.com|push\.apple\.com|windows\.com)/'),
  p256dh     text not null check (length(p256dh) <= 256),
  auth       text not null check (length(auth) <= 64),
  created_at timestamptz not null default now()
);

-- Row level security with no policy: the public key that ships in the page can neither read nor write the table.
alter table public.push_subscriptions enable row level security;

-- The page reaches the table only through these two functions.
create or replace function public.push_subscribe(endpoint text, p256dh text, auth text)
returns void language sql security definer set search_path = '' as $$
  insert into public.push_subscriptions (endpoint, p256dh, auth)
  values (push_subscribe.endpoint, push_subscribe.p256dh, push_subscribe.auth)
  on conflict (endpoint) do update set p256dh = excluded.p256dh, auth = excluded.auth;
$$;

create or replace function public.push_unsubscribe(endpoint text)
returns void language sql security definer set search_path = '' as $$
  delete from public.push_subscriptions s where s.endpoint = push_unsubscribe.endpoint;
$$;

revoke all on function public.push_subscribe(text, text, text) from public;
revoke all on function public.push_unsubscribe(text) from public;
grant execute on function public.push_subscribe(text, text, text) to anon;
grant execute on function public.push_unsubscribe(text) to anon;
