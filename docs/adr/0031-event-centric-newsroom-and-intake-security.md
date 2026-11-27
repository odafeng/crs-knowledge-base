# 0031. 事件導向 Newsroom 架構、ChatGPT News Radar 安全邊界與發布治理

## Status

Accepted（2026-11-27 維護者確認；[N0 #281](https://github.com/odafeng/crs-knowledge-base/issues/281)、[Job M · GutHub Newsroom 每日情報](https://github.com/odafeng/crs-knowledge-base/milestone/12)）。沿用 [ADR-0013](0013-gated-auto-publish.md) 事實查核原則、[ADR-0021](0021-single-content-writer-and-cutover.md) 單一內容寫入端、[ADR-0022](0022-engagement-and-gated-forum.md) LINE 每日推播與回訪原則、[ADR-0023](0023-web-push-through-the-api.md) Web Push 機制，並依賴 [ADR-0030](0030-specialty-taxonomy-and-topic-registry.md) 八大專科分類。

## Context

GutHub 既有內容管線包含 Paper Watch 實證文獻（`app.papers`）與 K2 #252 的自動論文新聞（`scripts/news_writer.py` → `app.news`）。然而高品質臨床試驗的發表頻率有限，單靠增加論文掃描次數無法滿足外科醫師對日常臨床情報的需求；同時，既有 `app.news` 強制綁定單一論文（`paper_id TEXT NOT NULL REFERENCES app.papers(id)`，且 `app.public_news` 以 `INNER JOIN app.papers` 查詢），無法容納沒有 PMID／DOI 的學會公告、FDA／TFDA 核准警示、台灣健保給付異動、臨床試驗狀態變更、指南更新與醫材／外科 AI 動態。

N0 架構審查同時確認三項關鍵風險：

1. **Issue #280 PoC 權限過廣**：2026-11-27 驗證的空批次 PoC（[Issue #280](https://github.com/odafeng/crs-knowledge-base/issues/280)，`schema_version: "1.0"`、`test_mode: true`、`publish_allowed: false`、`items: []`）係由維護者個人帳號 `odafeng` 建立。ChatGPT GitHub connector 若直接持有主程式碼庫擁有者權限，prompt 約束無法構成實質權限隔離，且與 `worker/content_requests.py` 信任的 `owner` 作者重疊。
2. **外部網頁與模型輸出均不可信**：事件新聞涵蓋異質網頁、新聞稿、預印本與試驗登錄，僅靠 `newsroom/gate.py` 的數字集合比對無法防範組別錯置、時間混用、跨司法管轄區推論、SSRF 或 prompt injection。
3. **審閱時間與通知疲勞限制**：維護者審閱時間有限，且既有 LINE 官方帳號已實施「每日 07:00 最多一則、無新內容不推」規則（ADR-0022）；Newsroom 不可另開第二條推播或繞過 Single Content Writer。

## Decision

### 1. 雙軌新聞共存與獨立事件資料模型

- **保留既有論文新聞（`app.news`）**：`scripts/news_writer.py`、`newsroom/gate.py`、`GET /api/v1/news` 與 `/news/[id]/` 100% 維持不變，繼續服務綁定單篇文獻的深度圖表專文。
- **新增事件導向資料模型**：於 `app` schema 建立獨立事件表群（RLS 僅授與 `guthub_api` 公開 view 讀權，草稿、內部評分、來源擷取片段與審核備註絕不外露）：
  - `app.news_ingest_batches`：記錄外部批次（`producer`, `batch_id`, `issue_id`, `payload_hash`, `schema_version`, `is_test`, `outcome`, `rejection_reason`），具唯一鍵與編輯衝突隔離。
  - `app.news_source_registry`：來源清單、URL、條款檢視日、polling interval、trust tier、enabled、健康狀態。
  - `app.news_candidates`：標準化候選紀錄與去重雜湊。
  - `app.news_events`、`app.news_event_sources`、`app.news_event_domains`（原生 FK 至 `app.domains`，具單一 primary partial unique index）：事件本體（`paper_id` 選填）、多來源佐證與八大專科關聯；事件分類採 8 種 event category（`research`、`clinical-trials`、`regulatory`、`taiwan-policy`、`guidelines`、`technology`、`academic-events`、`clinical-debate`），與專科領域正交分離。
  - `app.news_revisions`、`app.news_claims`、`app.news_review_actions`、`app.news_runs`：事件與文章修訂分離，更正或更新一律產生新 revision 保留歷史與完整審核稽核，不得無痕覆寫。
- **前端共存與 URL 結構**：
  - `/news/` 升級為統一新聞入口，整合「即時事件」與既有「論文專文」，支援依八大專科、事件類型與時間篩選。
  - 既有論文專文保留 `/news/[id]/` 與既有 Feed GUID；事件短訊使用 `/news/events/[id]/`，避免跨表 ID 碰撞與混淆。
  - 明確區分「本日尚無符合發布標準的新事件」與「部分來源更新延遲」，絕不以空日硬造新聞。

### 2. ChatGPT News Radar 安全邊界（獨立 Intake Repo）

- **Repo 層級物理隔離**：建立獨立專用 intake repo（例如 `odafeng/guthub-news-inbox`，不含任何程式碼、GitHub Actions workflows 或 secrets），專供 ChatGPT Scheduled Tasks 提交候選批次 Issues；Cloud Run worker 以 GitHub REST API 分頁單向唯讀輪詢該 repo。
- **既有流程防呆**：於主 repo 的 `worker/content_requests.py` 明確略過任何帶 `news-candidate` 或 `source:chatgpt` 標籤的 issue，並嚴禁於 Newsroom 流程重用 `accepted` 標籤。
- **Transport Contract（v1.0 相容 + v1.1 驗證）**：
  - 單一限定 fenced JSON 區塊解析、拒絕重複鍵、payload 上限 64 KB、嚴格型別與 `schema_version` / `taxonomy_version` 核對。
  - `test_mode !== false` 或 `publish_allowed !== true`（含缺失或型別錯誤）一律 fail closed 至 `app.news_ingest_batches (is_test = true)`，物理上無法進入候選、事件、公開 API、搜尋、Feed 或通知。
  - 已處理 issue 若遭編輯導致 `payload_hash` 變更，隔離為 `conflict_edited` 供人工審查，不靜默覆寫。
- **既有 `#280` 處置**：維持開啟以留存空批次 PoC 驗證紀錄，待 N1 於獨立 intake repo 完成合成非空批次測試後再結案。

### 3. 直接來源監測（N2 首批 6 來源）與 Collector 安全

為避免單一依賴 ChatGPT 排程，N2 建立 Source Registry 與首批 6 個直接來源 adapters：

1. 台灣健保署 + TFDA（重用並擴充既有 `scripts/regulatory_watch.py` 訊號，另補一般公告來源）
2. FDA Oncology Approvals（限定 CRS 相關）
3. ASCRS / ESCP
4. ClinicalTrials.gov API v2（比對實質狀態／結果異動，排除一般資料維護更新）
5. 台灣大腸直腸外科醫學會（`crs.org.tw`）
6. ERAS Society / ESGE（補齊非腫瘤專科覆蓋）

**Collector 安全與去重**：所有外部 URL（包含 ChatGPT 提供的候選）皆由後端 Collector 重新抓取原始頁面驗證，不採信外部摘要作為事實證據；強制實施 HTTPS-only、DNS 解析封鎖私網／loopback／link-local／cloud metadata IP（含每一跳 redirect 重驗）、大小與 timeout 上限、來源 allowlist。事件去重採確定性順序（來源 ID → DOI/PMID/NCT + 事件類型與版本 → 標準化標題與時間窗），不得將同一試驗的招募、主要結果與更正合併成無版本歷史的單一事件。

### 4. 撰稿、Event Verification Gate、風險分級與 Controlled Publisher

- **執行環境權限隔離**：撰稿 LLM（Writer）僅接收已擷取的來源內容與 schema，不具備資料庫正式表寫入權、GitHub 寫入權或通知發送憑證；所有外部文字均視為不可信資料，不拼接 shell 或工具命令。
- **模型與預算上限**：沿用既有 Anthropic API，為 Newsroom 設定獨立硬性額度——每月 LLM 預算上限 **USD 15–20**、每日最多處理 **10 則候選**／產出 **3 則草稿**；達上限即停止 LLM 生成但持續記錄來源健康狀況。
- **Event Verification Gate 與風險分級**：
  - 保留既有 `newsroom/gate.py` 不動，另建 event gate 查核原始來源可取得性、三種日期語意（事件／發稿／生效日）、數值與分母／組別／endpoint／CI 對應、司法管轄區（FDA／TFDA／NHI 不跨區類推）及證據狀態防誇大。
  - 分為 Low / Medium / High / Reject-Hold 四級；**Pilot 期間全人工審核**（auto-publish feature flag 初始關閉），目標每週人工審閱時間 **≤ 30 分鐘**（若超額優先調降候選上限，不放寬查核門檻）。任何歧義或安全異常一律 fail closed。
- **Controlled Publisher 與 Kill Switches**：
  - 審核介面擴充既有 `/admin/review/` 與 `app.content_requests`（支援 `kind = 'news_event'`），經由單一內容寫入端交易鎖（`guthub-content-writer`）、`app.publish_events` 冪等鍵與 `revalidate_site()` 即時刷新 ISR。
  - 提供四個獨立開關：`NEWSROOM_COLLECT_ENABLED`、`NEWSROOM_DRAFT_ENABLED`、`NEWSROOM_AUTO_PUBLISH_ENABLED`（預設 `false`）、`NEWSROOM_NOTIFY_ENABLED`（預設 `false`）。

### 5. 每日早報、Daily Clinical Insight 與既有通知整合

- **不新增第二個 LINE broadcast job**：擴充既有 `apps/api/src/guthub_api/daily.py` 與每日 07:00 `line-daily` job 納入已發布 `news_events`，維持「一天最多一則、無新內容不推、`X-Line-Retry-Key` 冪等」原則；協調 06:30 最後一次來源收集與 06:50 digest snapshot。
- **Daily Clinical Insight**：首頁以規則輪替既有已審閱文獻與證據卡片，明確標註「知識回顧」與複查日期，空領域不造稿，不偽裝成新事件亦不觸發新聞推播。
- **正式切換門檻**：須先於 staging / shadow mode 連續觀察至少 14 天，確認來源覆蓋率 100%、稽核樣本 critical claim failures = 0、審稿負擔與成本達標，並完成 kill-switch 演練，經維護者分別核准後才啟用正式排程（07:00/12:00/18:00 Asia/Taipei）、production 發布與通知開關。

## Consequences

### Positive

- 事件型新聞與既有論文新聞（`app.news`）職責清晰、資料模型互不干擾，100% 保留現有 Paper Watch 與 K2 論文新聞運作。
- 透過獨立 intake repo 徹底切斷 ChatGPT connector 對主程式碼庫的潛在權限風險。
- 嚴格遵守 ADR-0021 單一寫入端、ADR-0022 LINE 節制推播與 ADR-0024 staging 預演，不增加重複基礎設施。
- 硬性成本上限（USD 15–20/月）與審稿時間上限（≤ 30 分鐘/週）保護維護者精力與營運預算。

### Negative / Trade-offs

- 需維護一個額外的 intake repo（`guthub-news-inbox`）與跨 repo 輪詢設定，且維護者須先於 N1 階段手動建立該 repo 並重新綁定 ChatGPT connector。
- 雙軌新聞（`app.news` 與 `app.news_events`）使首頁、`/news/`、搜尋與 `daily.py` 需要整合兩種資料來源，查詢與前端元件略增複雜度。
- Pilot 階段採全人工審核且對所有外部候選重抓原始來源，發布延遲取決於維護者審閱頻率，且部分 paywall 或防爬蟲網站可能無法自動查核而改走人工判斷。

## References

- [N0 #281](https://github.com/odafeng/crs-knowledge-base/issues/281)、[Issue #280 PoC](https://github.com/odafeng/crs-knowledge-base/issues/280)、[N1 #286](https://github.com/odafeng/crs-knowledge-base/issues/286)–[N9 #294](https://github.com/odafeng/crs-knowledge-base/issues/294)、[Job M · GutHub Newsroom 每日情報](https://github.com/odafeng/crs-knowledge-base/milestone/12)
- [ADR-0013](0013-gated-auto-publish.md)、[ADR-0021](0021-single-content-writer-and-cutover.md)、[ADR-0022](0022-engagement-and-gated-forum.md)、[ADR-0023](0023-web-push-through-the-api.md)、[ADR-0024](0024-staging-for-schema-and-sign-in.md)、[ADR-0030](0030-specialty-taxonomy-and-topic-registry.md)
