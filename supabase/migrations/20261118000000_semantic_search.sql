-- H3 #125: natural-language search over the public papers, news and treatment cards (ADR-0022). Each item is
-- embedded with Voyage AI (voyage-4, 1024 dimensions) by scripts/search_index.py, which runs as the content owner;
-- the API only reads the vectors and counts the tokens its own query embeddings use. Query text is never stored.

create extension if not exists vector with schema extensions;

create table app.search_chunks (
  kind text not null check (kind in ('paper', 'news', 'card')),
  ref text not null check (ref <> ''),              -- paper id, news id, or "<topic key>#<card index>"
  path text not null check (path like '/%'),        -- the site page the result links to
  title text not null check (title <> ''),
  snippet text not null,                            -- shown under the title; the passage that was embedded
  content_hash text not null,                       -- sha256 of the embedded text: unchanged items are not re-embedded
  model text not null,
  embedding extensions.vector(1024) not null,
  indexed_at timestamptz not null default now(),
  primary key (kind, ref)
);

create index search_chunks_embedding on app.search_chunks using hnsw (embedding extensions.vector_cosine_ops);

-- Tokens sent to Voyage per calendar month (Asia/Taipei), by the indexer and by search queries together, so the
-- monthly cap covers both.
create table app.embedding_usage (
  month date primary key check (extract(day from month) = 1),
  tokens bigint not null default 0 check (tokens >= 0)
);

alter table app.search_chunks enable row level security;
alter table app.embedding_usage enable row level security;
revoke all on app.search_chunks, app.embedding_usage from public, anon, authenticated, service_role;
grant select on app.search_chunks to guthub_api;
grant select, insert, update on app.embedding_usage to guthub_api;
grant usage on schema extensions to guthub_api;
create policy guthub_api_read on app.search_chunks for select to guthub_api using (true);
create policy guthub_api_access on app.embedding_usage to guthub_api using (true) with check (true);
