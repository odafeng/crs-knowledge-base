# 0016. API、資料權威與雲端服務分工

**Status**: Accepted（2026-11-16 由維護者於 [A1 #53](https://github.com/odafeng/crs-knowledge-base/issues/53) 選定方案 A；production 切換另由 F4 核准）

## Context

現站以 JSON／HTML 為權威內容，GitHub Actions 執行 Python Paper Watch，網站建置產生 `site/`。新增使用者與留言後，需要可交易的持久資料、身分驗證、權限控制與可執行 API 的 hosting。

評估時有 Supabase 與全 Google Cloud 兩套候選。ADK 是 agent framework，Cloud Storage 是 object storage，Cloud SQL 是受管理的關聯式資料庫；它們分別處理不同責任，還需要網站執行環境與 Auth。

## Decision

採用方案 A：Next.js 前端 + Supabase（PostgreSQL／Auth／Storage）；既有 Python 服務（FastAPI 與 worker）按需部署 Cloud Run。

| 責任 | 採用 |
|---|---|
| 公開頁面與互動 UI | Next.js，部署於 Vercel（2026-11-17 維護者於 [F1 #75](https://github.com/odafeng/crs-knowledge-base/issues/75) 確認）；帳號與預算仍由 F1 提供 |
| 應用 API、寫入驗證、授權、管理流程 | FastAPI，部署於 Cloud Run |
| 文獻掃描、分類、發布任務 | Python worker，部署於 Cloud Run（jobs 或排程觸發） |
| 身分 | Supabase Auth |
| 內容與留言的權威資料庫 | Supabase PostgreSQL（唯一權威；不另設 Cloud SQL） |
| 檔案 | Supabase Storage |

Supabase Data API 不作為留言或內容的寫入入口；寫入一律經 FastAPI，避免繞過限速與審核規則。若前端直接讀取 Supabase，僅限公開 view，並以 RLS 驗證。帳號、區域、費用上限與祕密交付仍由 F1 確認。

### 資料庫存取與權限執行層（2026-11-16，B3 #60）

維護者選擇由 FastAPI 執行留言的身分規則，資料庫對外封閉：

- 資料表放在不對 Data API 公開的 `app` schema。`anon`、`authenticated` 對它沒有任何 grant，所有表也都開啟 RLS 且不給這兩個 role policy；即使日後誤把 `app` 加進公開 schema，仍讀不到資料。這些表也不加入 Realtime publication。
- FastAPI 以專用的 `guthub_api` role 連線。作者只能改自己的留言、管理者審核與查閱身分等規則只寫在 FastAPI，不在 SQL policy 再寫一份。作者／他人／訪客／管理者矩陣由 D2 經 API 對真實資料庫測試。
- 資料庫仍負責與身分無關的不變條件：foreign key、唯一鍵、狀態與欄位約束、帳號首則留言自動設為 `pending` 的 trigger，以及 `guthub_api` 只能新增、不能修改或刪除的 audit 表。

### 服務邊界

- Next.js 負責公開頁面、互動 component、session 相關呈現與必要的伺服器端整合。
- FastAPI 負責應用 API、寫入驗證、授權與管理流程；Python worker 執行文獻掃描、分類、來源查核及發布任務。長時間任務不放在留言 request 裡完成。
- `papers`、`news`、研究 `commentary` 與讀者 `comments` 分開建模。公開 DTO、管理 DTO 與私有作者對應分開處理。
- 一種業務寫入只設一個權威入口；不在 Next.js 與 FastAPI 各寫一套留言規則。若選 Supabase Data API，須與 FastAPI 使用相同政策，防止繞過權限或限速。
- 具體 API contract、部署服務數量與連線方式在 A1 後由 B1/B2 固定，不為尚未需要的服務建立抽象。

### 評估過的候選組合（記錄用）

| 責任 | A：建議起步方案 | B：全 Google Cloud |
|---|---|---|
| Next.js | Vercel 等支援 server 的 hosting | Firebase App Hosting |
| 身分 | Supabase Auth | Firebase Auth |
| PostgreSQL | Supabase PostgreSQL | Cloud SQL PostgreSQL |
| 檔案 | Supabase Storage | Cloud Storage |
| Python | FastAPI／worker，按需使用 Cloud Run | FastAPI／Cloud Run 與排程任務 |

A 的預期優點是 Auth、資料、Storage 的整合工作較少。B 適合已有 GCP 帳號、預算與 IAM 維運能力的情境。兩者都需依實際區域、流量、資料量與任務頻率估費，不在沒有使用量資料時承諾月費。

### 資料遷移與單一權威

1. 正式切換前，`data/papers.json`、`data/news.json` 與 `docs/` 仍為權威來源；資料庫只做可重建的匯入／staging 驗證。
2. 匯入提供 dry-run、數量與雜湊 manifest、重跑去重、關聯驗證及交易／還原程序。保留 paper ID、slug、DOI、來源、複查日期、review 狀態、關聯與詳細證據。
3. 在切換窗口凍結舊 writer，確認最後資料水位後啟用新的 PostgreSQL writer。GitHub Issues 的人工審核可繼續使用，但接受／撤下事件只能寫入新的權威資料。
4. PostgreSQL 成為內容與留言的單一權威後，JSON 若保留則為單向 export。不得讓 git 與資料庫接受獨立的雙向寫入。
5. rollback 必須處理切換後產生的留言及發布資料；不能單純回到舊靜態網站而遺失新寫入。

### 部署與驗收

- staging 與 production 使用彼此獨立的 Supabase project 與 Cloud Run service，各自設定預算與最小權限（2026-11-16 維護者於 [F1 #75](https://github.com/odafeng/crs-knowledge-base/issues/75) 確認）。
- 2026-11-17 維護者確認並已建立（F1 #75）：
  - **區域**：全部放東京。Supabase `ap-northeast-1`、Cloud Run `asia-northeast1`、Vercel 函式 `hnd1`，API 與資料庫同區。
  - **Supabase**：獨立組織 GutHub（Pro 方案，開啟 spend cap），專案 `guthub-staging` 與 `guthub-prod`。
  - **Google Cloud**：專案 `guthub-staging` 與 `guthub-prod`。每月預算 staging 320 TWD、prod 960 TWD（約 USD 10／30），在 50%、90%、100% 寄信通知；預算只通知，不會自動停止服務。
  - **Vercel**：專案 `guthub`，staging 用 Preview、production 用 Production 環境變數。
- **祕密**：只放在各環境的 Secret Manager，例如資料庫密碼與 API 的連線字串，並只授權給需要的執行身分；不寫進 repo、issue 或 README。
- **部署身分**：GitHub Actions 透過 OIDC 身分聯合取得 `deployer` 身分，不建立長期金鑰。只接受本 repo，production 只接受 `main`。`deployer` 只能部署 Cloud Run、推送映像，並以 `api-runtime`／`worker-runtime` 執行。
- **API 連線**：API 以只繼承 `guthub_api` 的 `guthub_api_login` 角色連線，已驗證它讀不到 `content_writer`、不能寫內容表、也碰不到 `auth` schema。
- GitHub Pages 可繼續服務現有靜態基線。完整的 Next.js server 與 FastAPI 另需選定 runtime；不把它們部署成 Pages 的靜態檔案。
- staging 通過內容 parity、unit/smoke/E2E、權限矩陣、mobile/accessibility 及還原演練後，才由 [F4 #79](https://github.com/odafeng/crs-knowledge-base/issues/79) 核准正式切換。
- 新依賴固定版本並提交 lockfile。前端建立 TypeScript/lint/unit/smoke/E2E，Python 維持 Ruff/Pyright/pytest。

### 部署流程（2026-11-17 補充；F4 #79）

- staging 與正式環境共用同一份部署步驟（`.github/workflows/deploy.yml`）。staging 在 `main` 有相關變更時自動部署；正式環境只能手動觸發 `deploy-prod.yml`，必須從 `main` 執行並輸入 `production` 確認。身分聯合本身也只接受 `main`。
- 每個環境的 job 開關（`LINE_ENABLED`、`PUSH_ENABLED`、`PAPER_WATCH_ENABLED`、`REGULATORY_WATCH_ENABLED`）與允許的網站來源（`WEB_ORIGINS`）設在對應的 GitHub environment，不用 repository 變數，開啟正式環境的功能不會影響 staging。正式環境的 CORS 名單不會沿用 staging 的設定。

## Consequences

- 部署步驟的改動會先在 staging 自動跑過，正式環境要到下次手動部署才套用。代價是兩個 GitHub environment 的變數要各自維護：忘了在某個環境設定開關，該 job 在那個環境就不會部署，而且不會報錯。
- API、長時間任務與資料寫入責任清楚，能重用現有 Python 程式。
- PostgreSQL 的交易與關聯約束可用來保護留言、審核狀態及發布的一致性。
- FastAPI 與 Next.js 帶來兩個 runtime，需維護 contract、部署、session 傳遞與監控。
- Supabase 將部分權限與產品整合綁在其服務上；全 GCP 則需要更多 IAM、連線、Auth 整合與費用管理工作。
- 匯入、單一 writer 切換與保留新留言的 rollback，比只搬靜態檔複雜；必須先在 staging 演練。
- FastAPI 跑在 Cloud Run、資料在 Supabase，兩者跨供應商連線，需處理連線池、延遲與兩邊的祕密管理。
- Google Cloud 的帳單帳戶有可連結專案數上限（預設 5 個）。GutHub 的兩個專案改掛在另一個帳單帳戶，該帳戶也因此滿額，日後新專案需要另外申請額度。
- 網站在 Vercel、API 在 Cloud Run、資料在 Supabase，三個供應商各有帳單、權限與祕密要管理；瀏覽器呼叫 API 是跨 origin，CORS 只允許網站的 origin（ADR-0020）。
- 身分規則只在 FastAPI 一處，維護簡單；代價是 API 若有越權漏洞（例如可改他人留言的 IDOR），資料庫不會再擋一次，所以 D2 的權限矩陣測試是主要防線。
- 本決策尚未建立雲端資源、執行 migration 或切換 production。

## References

- [A1 #53：雲端決策](https://github.com/odafeng/crs-knowledge-base/issues/53)
- [Job B：資料與 API](https://github.com/odafeng/crs-knowledge-base/milestone/2)
- [Job F：環境與正式切換](https://github.com/odafeng/crs-knowledge-base/milestone/6)
- [ADR-0006：JSON 資料來源](0006-json-single-source-of-truth.md)
- [Supabase 功能](https://supabase.com/docs/guides/getting-started/features)
- [Firebase App Hosting](https://firebase.google.com/docs/app-hosting)
- [Cloud SQL PostgreSQL](https://cloud.google.com/sql/docs/postgres/introduction)／[計費](https://cloud.google.com/sql/pricing)
- [Cloud Storage](https://cloud.google.com/storage/docs/introduction)
