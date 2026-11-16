-- B4 #61: keep source fields the public contract does not expose, so the database can become the authority at
-- cutover without losing data. metrics feeds the Paper Watch agents; soc_title is the treatment section heading;
-- source_file traces a paper's detail HTML back to its document under docs/.

alter table app.topics
  add column soc_title text,
  add column metrics jsonb check (metrics is null or jsonb_typeof(metrics) = 'object');

alter table app.papers
  add column source_file text check (source_file <> '');
