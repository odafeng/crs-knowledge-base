-- T1 #282 (ADR-0030): Versioned 8-specialty Central Topic Registry, backward-compatible app.topics
-- extension, multi-domain paper links (native FK + single primary constraint), and domain subscriptions.

create table app.domains (
  slug text primary key check (slug ~ '^[a-z0-9][a-z0-9-]*$'),
  sort_order smallint not null unique check (sort_order > 0),
  label_zh text not null check (char_length(btrim(label_zh)) > 0),
  label_en text not null check (char_length(btrim(label_en)) > 0),
  description_zh text not null check (char_length(btrim(description_zh)) > 0),
  status text not null default 'active' check (status in ('active', 'deprecated')),
  registry_version text not null check (char_length(btrim(registry_version)) > 0)
);

insert into app.domains (slug, sort_order, label_zh, label_en, description_zh, status, registry_version) values
  ('colorectal-oncology', 1, '大腸直腸腫瘤', 'Colorectal Oncology',
   'mCRC 分子精準治療、局部大腸直腸癌、TNT、器官保留、ctDNA、輔助治療與肛門癌。', 'active', '1.0'),
  ('anorectal-diseases', 2, '肛門疾病', 'Anorectal Diseases',
   '痔瘡、肛瘻、肛裂、肛門膿瘍、肛門狹窄與藏毛竇。', 'active', '1.0'),
  ('benign-colorectal-diseases', 3, '良性大腸疾病', 'Benign Colorectal Diseases',
   'IBD、克隆氏症、潰瘍性結腸炎、憩室疾病、大腸扭轉與非腫瘤性大腸急症。', 'active', '1.0'),
  ('pelvic-floor-functional', 4, '骨盆底與功能性疾病', 'Pelvic Floor & Functional Disorders',
   '便秘、糞便失禁、直腸脫垂、排便障礙、LARS 與肛門直腸生理檢查。', 'active', '1.0'),
  ('minimally-invasive-surgery', 5, '微創手術', 'Minimally Invasive Surgery',
   '腹腔鏡、機器手臂、TaTME、TME、CME、ICG 螢光導引與手術平台器械。', 'active', '1.0'),
  ('perioperative-care-nutrition', 6, '圍手術期照護與營養', 'Perioperative Care & Nutrition',
   'ERAS、術前預復健、營養與肌少症、感染預防、疼痛控制、吻合口滲漏與造口照護。', 'active', '1.0'),
  ('endoscopy', 7, '內視鏡', 'Endoscopy',
   '大腸鏡、EMR、ESD、EFTR、息肉切除、內視鏡併發症與 AI 輔助內視鏡。', 'active', '1.0'),
  ('surgical-intelligence', 8, '外科智慧', 'Surgical Intelligence',
   '術前風險與難度預測、CT 骨盆測量、術中影像辨識、外科資料科學與醫療 AI 安全。', 'active', '1.0');

-- Subtopics map curated legacy topics and future specialty subtopics onto the 8 domains.
-- legacy_topic_key intentionally omits an FK to app.topics so migrations apply cleanly on empty databases
-- prior to content seeding; parity is enforced by tests/test_taxonomy_registry.py.
create table app.subtopics (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]*$'),
  parent_domain text not null references app.domains (slug),
  slug text not null check (slug ~ '^[a-z0-9][a-z0-9-]*$'),
  label_zh text not null check (char_length(btrim(label_zh)) > 0),
  label_en text not null check (char_length(btrim(label_en)) > 0),
  legacy_topic_key text unique check (legacy_topic_key is null or legacy_topic_key ~ '^[A-Za-z0-9][A-Za-z0-9-]*$'),
  route_path text check (route_path is null or route_path like '/%'),
  sort_order smallint not null check (sort_order > 0),
  status text not null default 'active' check (status in ('active', 'legacy_compat', 'deprecated')),
  registry_version text not null check (char_length(btrim(registry_version)) > 0),
  unique (parent_domain, slug)
);

insert into app.subtopics
  (id, parent_domain, slug, label_zh, label_en, legacy_topic_key, route_path, sort_order, status, registry_version)
values
  ('mcrc-braf-v600e', 'colorectal-oncology', 'braf-v600e', 'BRAF V600E', 'BRAF V600E mCRC', 'mCRC-BRAF-V600E', '/mcrc/braf-v600e/', 1, 'active', '1.0'),
  ('mcrc-kras-g12c', 'colorectal-oncology', 'kras-g12c', 'KRAS G12C', 'KRAS G12C mCRC', 'mCRC-KRAS-G12C', '/mcrc/kras-g12c/', 2, 'active', '1.0'),
  ('mcrc-msi-h', 'colorectal-oncology', 'msi-h', 'MSI-H / dMMR', 'MSI-H / dMMR CRC', 'mCRC-MSI-H', '/mcrc/msi-h/', 3, 'active', '1.0'),
  ('mcrc-her2', 'colorectal-oncology', 'her2', 'HER2', 'HER2-Positive mCRC', 'mCRC-HER2', '/mcrc/her2/', 4, 'active', '1.0'),
  ('mcrc-ras-wt', 'colorectal-oncology', 'ras-wt', 'RAS wild-type', 'RAS Wild-Type mCRC', 'mCRC-RAS-wt', '/mcrc/ras-wt/', 5, 'active', '1.0'),
  ('mcrc-later-line', 'colorectal-oncology', 'later-line', '後線治療', 'Later-Line & Cross-Biomarker mCRC', 'generic-CRS', '/mcrc/later-line/', 6, 'legacy_compat', '1.0'),
  ('colorectal-tnt-organ-preservation', 'colorectal-oncology', 'tnt-organ-preservation', '直腸癌 TNT 與器官保留', 'Rectal Cancer TNT & Organ Preservation', null, null, 7, 'active', '1.0'),
  ('colorectal-ctdna-adjuvant', 'colorectal-oncology', 'ctdna-adjuvant', 'ctDNA 與輔助治療', 'ctDNA & Adjuvant Therapy', null, null, 8, 'active', '1.0'),
  ('anal-cancer', 'colorectal-oncology', 'anal-cancer', '肛門癌', 'Anal Cancer', null, null, 9, 'active', '1.0'),
  ('anorectal-benign-procedures', 'anorectal-diseases', 'anorectal-benign', '痔瘡、肛瘻與肛裂', 'Hemorrhoids, Fistula & Fissure', null, null, 1, 'active', '1.0'),
  ('anorectal-sepsis-pilonidal', 'anorectal-diseases', 'sepsis-pilonidal', '肛門膿瘍與藏毛竇', 'Anorectal Sepsis & Pilonidal Disease', null, null, 2, 'active', '1.0'),
  ('ibd-surgery', 'benign-colorectal-diseases', 'ibd-surgery', '發炎性腸道疾病外科', 'IBD Surgery', null, null, 1, 'active', '1.0'),
  ('diverticular-emergency', 'benign-colorectal-diseases', 'diverticular-emergency', '憩室疾病與大腸急症', 'Diverticular Disease & Colorectal Emergencies', null, null, 2, 'active', '1.0'),
  ('lars-incontinence', 'pelvic-floor-functional', 'lars-incontinence', 'LARS 與糞便失禁', 'LARS & Fecal Incontinence', null, null, 1, 'active', '1.0'),
  ('prolapse-constipation', 'pelvic-floor-functional', 'prolapse-constipation', '直腸脫垂與排便障礙', 'Rectal Prolapse & Obstructed Defecation', null, null, 2, 'active', '1.0'),
  ('robotic-mis', 'minimally-invasive-surgery', 'robotic', '機器手臂與微創手術', 'Robotic & Minimally Invasive Colorectal Surgery', 'robotic-surgery', '/robotic/', 1, 'active', '1.0'),
  ('eras-prehab-nutrition', 'perioperative-care-nutrition', 'eras-nutrition', 'ERAS、營養與預復健', 'ERAS, Nutrition & Prehabilitation', null, null, 1, 'active', '1.0'),
  ('anastomotic-leak-stoma', 'perioperative-care-nutrition', 'leak-stoma', '吻合口滲漏與造口照護', 'Anastomotic Leakage & Stoma Care', null, null, 2, 'active', '1.0'),
  ('esd-emr-polypectomy', 'endoscopy', 'esd-emr', 'ESD、EMR 與 EFTR', 'ESD, EMR, EFTR & Polypectomy', null, null, 1, 'active', '1.0'),
  ('ai-endoscopy', 'endoscopy', 'ai-endoscopy', 'AI 輔助內視鏡', 'AI-Assisted Endoscopy', null, null, 2, 'active', '1.0'),
  ('surgical-risk-prediction', 'surgical-intelligence', 'risk-prediction', '術前風險與影像預測', 'Risk Prediction & CT Pelvimetry', null, null, 1, 'active', '1.0'),
  ('intraoperative-vision-ai', 'surgical-intelligence', 'intraoperative-ai', '術中影像與外科資料科學', 'Intraoperative Vision & Surgical Data Science', null, null, 2, 'active', '1.0');

-- Backward-compatible extension of app.topics (ADR-0030): keep the 7 legacy subtopics intact and add
-- kind='domain' rows for the 6 newly introduced domains so Paper Watch T4 can publish without breaking
-- app.papers.topic_key NOT NULL.
alter table app.topics
  add column kind text not null default 'legacy_subtopic' check (kind in ('legacy_subtopic', 'domain')),
  add column domain_slug text references app.domains (slug);

update app.topics
set domain_slug = case
  when key in ('mCRC-BRAF-V600E', 'mCRC-KRAS-G12C', 'mCRC-MSI-H', 'mCRC-HER2', 'mCRC-RAS-wt', 'generic-CRS')
    then 'colorectal-oncology'
  when key = 'robotic-surgery'
    then 'minimally-invasive-surgery'
  else domain_slug
end
where domain_slug is null;

insert into app.topics (key, slug, label, title, kind, domain_slug) values
  ('anorectal-diseases', 'anorectal-diseases', '肛門疾病', '肛門疾病 Anorectal Diseases', 'domain', 'anorectal-diseases'),
  ('benign-colorectal-diseases', 'benign-colorectal-diseases', '良性大腸疾病', '良性大腸疾病 Benign Colorectal Diseases', 'domain', 'benign-colorectal-diseases'),
  ('pelvic-floor-functional', 'pelvic-floor-functional', '骨盆底與功能性疾病', '骨盆底與功能性疾病 Pelvic Floor & Functional Disorders', 'domain', 'pelvic-floor-functional'),
  ('perioperative-care-nutrition', 'perioperative-care-nutrition', '圍手術期照護與營養', '圍手術期照護與營養 Perioperative Care & Nutrition', 'domain', 'perioperative-care-nutrition'),
  ('endoscopy', 'endoscopy', '內視鏡', '內視鏡 Endoscopy', 'domain', 'endoscopy'),
  ('surgical-intelligence', 'surgical-intelligence', '外科智慧', '外科智慧 Surgical Intelligence', 'domain', 'surgical-intelligence')
on conflict (key) do nothing;

-- Multi-domain classification links for papers (single canonical paper, 1 primary + 0..N secondary domains).
create table app.paper_domains (
  paper_id text not null references app.papers (id) on delete cascade,
  domain_slug text not null references app.domains (slug),
  is_primary boolean not null default false,
  subtopic_id text references app.subtopics (id),
  tags text[] not null default '{}',
  taxonomy_version text not null check (char_length(btrim(taxonomy_version)) > 0),
  assigned_by text not null check (char_length(btrim(assigned_by)) > 0),
  assigned_at timestamptz not null default now(),
  primary key (paper_id, domain_slug)
);

-- Guarantees at most one primary_domain per paper at the database level.
create unique index paper_domains_one_primary on app.paper_domains (paper_id) where is_primary;
create index paper_domains_domain_idx on app.paper_domains (domain_slug, is_primary);

-- Specialty-level subscriptions, separate from legacy fine-grained app.topic_subscriptions (ADR-0030).
create table app.domain_subscriptions (
  account_id uuid not null references app.accounts (id) on delete cascade,
  domain_slug text not null references app.domains (slug),
  created_at timestamptz not null default now(),
  primary key (account_id, domain_slug)
);

-- Privileges and RLS: match ADR-0016/0017/0021 boundaries.
revoke all on app.domains, app.subtopics, app.paper_domains, app.domain_subscriptions
  from public, anon, authenticated, service_role;

grant select on app.domains, app.subtopics, app.paper_domains to guthub_api;
grant select, insert, delete on app.domain_subscriptions to guthub_api;

do $$
declare t text;
begin
  foreach t in array array['domains', 'subtopics', 'paper_domains', 'domain_subscriptions'] loop
    execute format('alter table app.%I enable row level security', t);
    execute format('create policy guthub_api_access on app.%I to guthub_api using (true) with check (true)', t);
  end loop;
end $$;
