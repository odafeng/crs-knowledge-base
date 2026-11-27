# 0030. 八大專科共用分類架構、Central Topic Registry 與向後相容遷移

## Status

Accepted（2026-11-27 維護者確認；[N0 #281](https://github.com/odafeng/crs-knowledge-base/issues/281)、[Job L · 專科分類重構](https://github.com/odafeng/crs-knowledge-base/milestone/11)）。承接 [ADR-0028](0028-colorectal-surgery-scope-and-robotic-papers.md) 延後處理的外科分類命名與結構問題，並遵守 [ADR-0021](0021-single-content-writer-and-cutover.md) 單一內容寫入端與 [ADR-0027](0027-retire-static-site-and-read-postgres-directly.md) 直接讀取 PostgreSQL 的邊界。

## Context

GutHub 既有的 7 個分類（`mCRC-BRAF-V600E`、`mCRC-KRAS-G12C`、`mCRC-MSI-H`、`mCRC-HER2`、`mCRC-RAS-wt`、`generic-CRS`、`robotic-surgery`）源自維護者個人追蹤 mCRC 分子標記與機器手臂手術的需求。將產品擴展為面向全體大腸直腸外科醫師的知識庫與每日情報平台時，現有結構面臨四項瓶頸：

1. **第一層導航嚴重偏斜**：7 個主題中有 5 個是 mCRC 分子亞型、1 個是雜項桶（`generic-CRS`），缺乏肛門疾病、良性大腸疾病（IBD／憩室／急症）、骨盆底與功能性疾病、圍手術期照護與營養、內視鏡及外科智慧等專科領域。
2. **單一 FK 限制跨領域內容**：`app.papers.topic_key` 為 1:1 `NOT NULL` 外鍵，無法將一篇「深度學習預測機器手臂 TME 術後吻合口滲漏」的文獻同時歸類於多個專科而不複製文章。
3. **Hardcoded 分類散落全端**：7 個 legacy keys 硬編碼在 `scripts/topics.py`、`scripts/queries.json`、`import_content.py`、`contracts/openapi.yaml`、`apps/api/src/guthub_api/content.py`、Next.js 的 `mcrc` vs `robotic` 二分法，以及 `app.topic_subscriptions`、`app.forum_posts`、`pg_trgm` 與 Voyage 搜尋索引。
4. **必須 100% 維持既有資料與功能相容**：既有 mCRC 治療卡片（`standard_of_care`）、台灣健保／TFDA 核准狀態（`regulatory`）、tumor board 一頁摘要、`/mcrc/*` 與 `/robotic/*` 網址、Feed GUID（`tag:odafeng.github.io,2026:`）與既有的細粒度主題訂閱都已投入正式運作，不得無預警破壞或擅自擴大訂閱範圍。

## Decision

### 1. 八大專科領域（Stable Domain Slugs）

以以下 8 個穩定英文 slug 作為全站內容（文獻、新聞事件、搜尋、論壇、訂閱）共用的第一層專科分類；中文顯示名稱可微調，slug 一經發布不隨 UI 文案變動：

| 順序 | Domain slug | 中文名稱 | English Name | 邊界說明 |
| --- | --- | --- | --- | --- |
| 1 | `colorectal-oncology` | 大腸直腸腫瘤 | Colorectal Oncology | mCRC（含原有五大分子標記與後線治療）、局部大腸癌、直腸癌、TNT、watch-and-wait、器官保留、ctDNA、輔助治療、篩檢追蹤、**肛門癌** |
| 2 | `anorectal-diseases` | 肛門疾病 | Anorectal Diseases | 痔瘡、肛瘻、肛裂、肛門膿瘍、狹窄、藏毛竇 |
| 3 | `benign-colorectal-diseases` | 良性大腸疾病 | Benign Colorectal Diseases | IBD、Crohn's disease、ulcerative colitis、憩室疾病、volvulus、非腫瘤性阻塞與大腸急症 |
| 4 | `pelvic-floor-functional` | 骨盆底與功能性疾病 | Pelvic Floor & Functional Disorders | 便秘、糞便失禁、直腸脫垂、排便障礙、LARS、肛門直腸生理檢查 |
| 5 | `minimally-invasive-surgery` | 微創手術 | Minimally Invasive Surgery | 腹腔鏡、robotic、TaTME、TME、CME、ICG、手術器械與平台 |
| 6 | `perioperative-care-nutrition` | 圍手術期照護與營養 | Perioperative Care & Nutrition | ERAS、nutrition、prehabilitation、sarcopenia、immunonutrition、感染預防、疼痛控制、**吻合口滲漏與造口照護**（涉及微創技術時加 `minimally-invasive-surgery` 為 secondary） |
| 7 | `endoscopy` | 內視鏡 | Endoscopy | colonoscopy、EMR、ESD、EFTR、polypectomy、內視鏡影像與併發症、AI-assisted endoscopy |
| 8 | `surgical-intelligence` | 外科智慧 | Surgical Intelligence | 術前風險／難度預測、CT pelvimetry、術中影像與 phase recognition、術後監測、surgical data science、自主手術、醫療 AI 安全（特色專區，不凌駕其他七類） |

**正交維度分離**：專科領域（Domain）、內容型態（`paper` / `paper_news` / `news_event` / `clinical_insight` / `forum_thread`）與新聞事件類型（見 [ADR-0031](0031-event-centric-newsroom-and-intake-security.md)）各自獨立；研究設計與 evidence status 另存欄位，不作專科分類。

### 2. 版本化 Central Topic Registry

- 新增單一真源檔案 `contracts/taxonomy.json`（起始版本 `1.0`），定義 8 個 `domains`、既有與新增 `subtopics`（含 `legacyTopicKey` 與路由映射）、受控 `tags` 與 `aliases`。
- Python（API、Paper Watch、Newsroom worker）直接載入打包於映像內的 `contracts/taxonomy.json`；TypeScript（`apps/web`）透過 `npm run contract:generate` 產生型別並由 CI 的 `contract:check` 驗證雙邊一致性。
- 任何外部輸入（如 ChatGPT News Radar）僅能提供分類 hint，後端強制核對 `taxonomy_version` 與 registry slug；未知版本或未知 slug 一律 fail closed，送人工分類佇列，不自動建立新 slug，亦不再退回 `generic-CRS`。

### 3. 資料庫與 API 向後相容模型

- **Registry 投影表**：新增 `app.domains` 與 `app.subtopics`（含 `legacy_topic_key UNIQUE REFERENCES app.topics(key)` 與 `parent_domain REFERENCES app.domains(slug)`），RLS 僅授與 `guthub_api` 唯讀權限（`SELECT`）。
- **單一 Canonical Record 與多領域關聯**：
  - 新增 `app.paper_domains (paper_id REFERENCES app.papers(id) ON DELETE CASCADE, domain_slug REFERENCES app.domains(slug), is_primary BOOLEAN NOT NULL, subtopic_id REFERENCES app.subtopics(id), tags TEXT[] NOT NULL DEFAULT '{}', taxonomy_version TEXT NOT NULL, assigned_by TEXT NOT NULL, assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (paper_id, domain_slug))`。
  - 建立 partial unique index `CREATE UNIQUE INDEX paper_domains_one_primary ON app.paper_domains (paper_id) WHERE is_primary;`，由資料庫原生約束保證每篇文獻最多一個 `primary_domain`、無重複領域且具備完整 FK 完整性。
  - 跨領域文獻只存在一筆 `app.papers` 紀錄、一個 URL 與一個 Feed GUID，於多個專科頁可見。
  - 既有論文新聞（`app.news`）透過 `paper_id` 繼承論文的專科關聯，不另複製。
- **`app.topics` 與 `app.papers.topic_key` 相容策略**：
  - 保留 `app.papers.topic_key NOT NULL REFERENCES app.topics(key)` 與既有 7 列 `app.topics`（保留其 `standard_of_care`、`regulatory`、`robotic_sections` 與 `tumor-board` 支援）。
  - 於 `app.topics` 新增 `kind TEXT NOT NULL DEFAULT 'legacy_subtopic' CHECK (kind IN ('legacy_subtopic', 'domain'))` 與 `domain_slug TEXT REFERENCES app.domains(slug)`，並為其餘 6 個新領域補齊 `kind = 'domain'` 之資料列，使 T4 擴充 Paper Watch 時既有寫入流程（`content_store.py` / `import_content.py`）與 OpenAPI 必填欄位 `Paper.topic` 維持零中斷。
  - OpenAPI 與 FastAPI 維持既有 `/api/v1/topics`、`/api/v1/papers?topic=`、`/api/v1/me/topics` 行為不變；新增 `GET /api/v1/domains`、`GET /api/v1/papers?domain=`、於 `Paper` 回傳 `primaryDomain` / `secondaryDomains` / `subtopics`。
- **訂閱分離保護**：保留 `app.topic_subscriptions` 與 `GET/PUT /api/v1/me/topics`（現有 mCRC 細粒度訂閱範圍不變，不擅自擴大為全腫瘤訂閱）；新增 `app.domain_subscriptions` 與 `GET/PUT /api/v1/me/domains` 供讀者訂閱八大專科。

### 4. 前端 URL 結構與遷移策略

- **網址規劃**：
  - 新增 `/specialties/[domain]/` 作為八大專科主頁。
  - `/topics/` 升級為「八大專科總覽 + 深層專題（mCRC 分子標記／機器手臂／藥物）」；首頁新增「Explore by Specialty」。
  - 100% 保留 `/mcrc/*`、`/robotic/`、`/robotic/tme/`、`/robotic/anastomosis/`、`/tumor-board/*`、`/drugs/*`、`/papers/[slug]/`、`/news/[id]/` 與 `/feed/*.xml`、`/rss.xml`、`/atom.xml`、`/feed.json`（Feed GUID `tag:odafeng.github.io,2026:` 不變）；舊專題頁以麵包屑連結回所屬專科。
  - 尚無文獻的專科頁誠實標示狀態，不呈現空洞假卡。
- **遷移流程（Expand → Backfill → Verify → Switch → Contract）**：
  1. **Expand（T1）**：新增 registry、新表與 additive API，先經 `deploy-staging.yml` 演練（ADR-0024）。
  2. **Backfill（T2）**：唯讀掃描 live PostgreSQL 全量 `app.papers` 產出 `mapping-manifest.json`。5 個 `mCRC-*` 對應 `colorectal-oncology` 各自 subtopic；`robotic-surgery` 預設候選 `minimally-invasive-surgery`（含 AI／影像預測標記人工覆核）；`generic-CRS` 逐筆分類並由維護者人工覆核歧義條目。經核可後在單一交易由 content-owner role 套用，驗證 100% active papers 恰有一個 primary domain 且既有資料零遺失。
  3. **Switch（T3）**：切換前端導覽、搜尋（`pg_trgm` + Voyage `search_index.py` + 離線 `search.json`）、論壇與訂閱介面。
  4. **Rollback**：因 Expand 與 Backfill 為純 additive 且不動既有欄位，可透過 feature flag 切回舊前端視圖而不刪資料，也不回寫已退役的靜態 JSON。
  5. **Contract**：本階段不刪除 legacy keys 或舊路由，日後另行授權。

### 5. Paper Watch 分批擴充順序（T4）

在 `colorectal-oncology` 與 `minimally-invasive-surgery` 已有覆蓋的基礎上，解除 `scripts/queries.json` 與 UI taxonomy 的一對一綁定，並廢止 `scripts/fetch_rss.py` 預設硬塞 `generic-CRS` 的行為。其餘 6 領域分三批先以 `--dry-run` / shadow mode 驗證 precision、跨領域去重與成本，且不放寬 [ADR-0013](0013-gated-auto-publish.md) provenance gate 與 [ADR-0029](0029-autonomous-paper-watch-self-repair.md) self-repair 門檻：

1. **第 1 批**：`perioperative-care-nutrition`、`endoscopy`
2. **第 2 批**：`anorectal-diseases`、`benign-colorectal-diseases`
3. **第 3 批**：`pelvic-floor-functional`、`surgical-intelligence`

## Consequences

### Positive

- 全站文獻、新聞事件、搜尋、論壇與訂閱共用同一份版本化八大專科分類，消除多處硬編碼與命名漂移。
- 跨專科文獻以單一 canonical record 搭配原生 FK 關聯表呈現，避免重複條目與重複推播。
- 既有 mCRC 分子標記深度證據卡、健保／TFDA 核准狀態、舊網址、Feed GUID 與細粒度訂閱 100% 向後相容，無中斷遷移風險。
- 階段式 Expand → Backfill → Verify → Switch 配合 staging 預演，讓維護者可先逐筆確認 `generic-CRS` 與 AI 研究歸屬再套用。

### Negative / Trade-offs

- 過渡期間並存 `app.topics`（含 `legacy_subtopic` 與 `domain` 列）與 `app.domains` / `app.paper_domains`，資料模型多一層對應概念，需透過 CI 與 migration 測試保證兩者不脫鉤。
- 寫入層 `content_store.py` / `import_content.py` 需明確保留並同步 `app.paper_domains`，不可在重寫 `papers` 時遺漏或覆寫多領域關聯。
- 帳號訂閱頁同時保留「八大專科」與「既有 mCRC 細粒度主題」兩組選項，UI 須清楚區分層級，避免新讀者困惑。
- 擴充 6 個新領域至 Paper Watch 會增加 PubMed 候選數與 Claude 分類費用，須透過分批 shadow 測試與成本監控控管。

## References

- [N0 #281](https://github.com/odafeng/crs-knowledge-base/issues/281)、[T1 #282](https://github.com/odafeng/crs-knowledge-base/issues/282)、[T2 #283](https://github.com/odafeng/crs-knowledge-base/issues/283)、[T3 #284](https://github.com/odafeng/crs-knowledge-base/issues/284)、[T4 #285](https://github.com/odafeng/crs-knowledge-base/issues/285)、[Job L · 專科分類重構](https://github.com/odafeng/crs-knowledge-base/milestone/11)
- [ADR-0013](0013-gated-auto-publish.md)、[ADR-0021](0021-single-content-writer-and-cutover.md)、[ADR-0024](0024-staging-for-schema-and-sign-in.md)、[ADR-0027](0027-retire-static-site-and-read-postgres-directly.md)、[ADR-0028](0028-colorectal-surgery-scope-and-robotic-papers.md)、[ADR-0029](0029-autonomous-paper-watch-self-repair.md)、[ADR-0031](0031-event-centric-newsroom-and-intake-security.md)
