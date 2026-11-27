# GutHub

大腸直腸外科實證知識庫與專業討論平台（原名 **Seminar Hegemon**）。

正式網站位於 **<https://guthub.tw>**，採 **Next.js + TypeScript + React** 前端（Vercel）、**FastAPI** 與 **Python workers**（Google Cloud Run）及 **Supabase PostgreSQL + Auth**（`app` schema 隔離，`data/WRITER = postgres`）。既有靜態網站建置管線（`build.py`、`sitegen/`、`templates/`、`static/` 與 GitHub Pages 部署）已於 [ADR-0027](docs/adr/0027-retire-static-site-and-read-postgres-directly.md) 退役。

[CI](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml) · [Deploy staging](https://github.com/odafeng/crs-knowledge-base/actions/workflows/deploy-staging.yml) · [Deploy production](https://github.com/odafeng/crs-knowledge-base/actions/workflows/deploy-prod.yml) · [Jobs / milestones](https://github.com/odafeng/crs-knowledge-base/milestones) · [Issues](https://github.com/odafeng/crs-knowledge-base/issues)

> 內容供醫療專業人員教育與臨床參考，不構成醫療建議。AI 整理與新聞稿的查核範圍有限，臨床判斷請回到原始文獻及現行指引。

## 目前功能

- **實證文獻與治療卡片**：依分子標記、藥物與微創外科主題瀏覽文獻、詳細證據、繁中白話重點摘要（ADR-0025）、治療路徑、Tumor board 一頁摘要及台灣 TFDA／健保核准給付現況（保留來源與複查日期）。
- **AI 新聞稿與每日精選**：Paper Watch 自動為高影響力新文獻產出結構化繁中新聞稿（經 `newsroom/gate.py` 數字查核後寫入 `app.news`），未經人工審核之條目標示「AI 未審」並設 `noindex`；首頁提供「今天的一件事」與每日 07:00 LINE 官方帳號推播（有新內容才推、一天最多一則）。
- **搜尋與離線閱讀**：支援 PostgreSQL `pg_trgm` 關鍵字搜尋、Voyage AI（`voyage-4`）自然語言語意搜尋，以及公開內容 Service Worker 離線閱讀與深色模式／字級調整。
- **登入、留言與驗證會員論壇**：支援 Email 一次性連結與 Google 登入；署名／匿名文獻留言與按讚；經專科驗證之大腸直腸外科醫師會員專屬論壇（不公開、不進搜尋引擎與公開快取）。
- **自動化文獻監測**：Cloud Run `paper-watch` 每日 16:00 掃描 PubMed 與期刊，通過 provenance gate（含最多 2 次有界 AI self-repair，ADR-0029）者自動發布並標為 `auto`；管理者可於 `/admin/review/` 標為已審或撤下。
- **Feed 與訂閱**：提供 RSS（`/rss.xml`、`/feed/*.xml`）、Atom（`/atom.xml`）、JSON Feed（`/feed.json`）、站內主題訂閱與追蹤文獻 Email 每日彙整通知。

## 部署架構

正式環境與 staging 共用 `.github/workflows/deploy.yml`（透過 GitHub OIDC 登入 Google Cloud，無長期金鑰）：

| 環境 | GCP 專案 | Supabase Ref | 觸發方式 |
| --- | --- | --- | --- |
| Staging | `guthub-staging` | `dlfhqneoqxlelczqcxif` | `main` 上有 migration、Supabase 設定、認證或部署檔變更時自動執行（`deploy-staging.yml`） |
| Production | `guthub-prod` | `pcmxouxeaoqvvegbclfg` | 僅限維護者手動觸發 `deploy-prod.yml`（確認輸入 `production`），且須先通過 staging 預演檢查（ADR-0024） |

前端（`apps/web/`）部署於 Vercel（正式網域 `https://guthub.tw`）；後端待部署變更由 `.github/workflows/deploy-pending.yml` 自動追蹤。詳細維運與還原程序見 [`docs/runbook-cutover.md`](docs/runbook-cutover.md)。

Cloud Run 服務與排程 jobs 皆由 GitHub environment 變數控制（`PAPER_WATCH_ENABLED`、`CONTENT_REQUESTS_ENABLED`、`LINE_ENABLED`、`PUSH_ENABLED`、`SEARCH_ENABLED`、`REGULATORY_WATCH_ENABLED`、`COMMENT_DIGEST_ENABLED`、`REVALIDATE_ENABLED`、`SURGEON_AUTO_APPROVE`）：

- `guthub-api`：公開讀取與認證互動 API（`guthub_api` 角色無內容表寫入權）。
- `paper-watch`：每日 16:00（Asia/Taipei）直接讀取 PostgreSQL 執行完整掃描並寫入新文獻與自動新聞稿。
- `content-requests`：處理 `/admin/review/` 審核／撤下按鈕與 GitHub Issue 人工請求（Single Content Writer，ADR-0021）。
- `search-index`：每日 01:30 更新 Voyage AI 語意向量索引。
- `purge-deleted-authors`：每日 03:30 清除已刪除超過 90 天之留言／論壇作者對應與帳號。
- `line-daily`（07:00）、`comment-digest`（07:30）、`announce-news`（每 30 分鐘，視 `PUSH_ENABLED`）、`regulatory-watch`（每週一 09:00，視 `REGULATORY_WATCH_ENABLED`）。

## 建置工作如何追蹤

**Jobs 使用 milestones，Steps 使用 issues。** 依賴、驗收條件、負責人與討論放在 GitHub Issues；README 僅提供入口，不另維護待辦清單。

| Job | 工作範圍 | GitHub milestone |
| --- | --- | --- |
| A | 決策、上線基線、README 與 ADR | [GutHub 決策與上線基線](https://github.com/odafeng/crs-knowledge-base/milestone/1) |
| B | 資料／API contract、FastAPI、schema、權限與內容匯入 | [資料模型與 API](https://github.com/odafeng/crs-knowledge-base/milestone/2) |
| C | Next.js 閱讀頁面、搜尋、公開內容離線與品牌 | [Next.js 閱讀介面](https://github.com/odafeng/crs-knowledge-base/milestone/3) |
| D | 登入、署名／匿名留言、防濫用與檢舉審核 | [身分與留言](https://github.com/odafeng/crs-knowledge-base/milestone/4) |
| E | Paper Watch 遷移、Single Content Writer 與審閱佇列 | [Paper Watch 遷移](https://github.com/odafeng/crs-knowledge-base/milestone/5) |
| F | 雲端環境、staging、還原演練與正式切換 | [環境、驗收與正式切換](https://github.com/odafeng/crs-knowledge-base/milestone/6) |
| G | LINE 每日推送、今天的一件事、健保／TFDA 異動監測、主題訂閱、tumor board 摘要 | [回訪與觸及](https://github.com/odafeng/crs-knowledge-base/milestone/7) |
| H | 留言按讚、自然語言語意搜尋與驗證醫師論壇 | [討論與語意搜尋](https://github.com/odafeng/crs-knowledge-base/milestone/8) |
| I | 文獻頁繁中白話摘要（一眼看懂） | [文獻頁一眼看懂](https://github.com/odafeng/crs-knowledge-base/milestone/9) |
| K | 架構整理、ISR、pg_trgm 搜尋、靜態站退役、外科範圍擴充與自動化優化 | [架構與自動化優化](https://github.com/odafeng/crs-knowledge-base/milestone/10) |
| L | 八大專科共用分類架構、Central Topic Registry、向後相容遷移與 Paper Watch 擴充 | [專科分類重構（Taxonomy）](https://github.com/odafeng/crs-knowledge-base/milestone/11) |
| M | 事件導向 Newsroom、ChatGPT News Radar 安全接入、來源監測、審核發布與每日早報 | [GutHub Newsroom 每日情報](https://github.com/odafeng/crs-knowledge-base/milestone/12) |

開始工作前，先讀對應 milestone 的 open issues。`[me]` 是 agent 可執行的工作；`[wait]` 需先完成列出的依賴；`[you]` 是維護者需決定或提供資源的事項。規劃 issues 僅使用 `blocked`、`needs-decision` 狀態標籤。

```bash
gh issue list --repo odafeng/crs-knowledge-base --milestone 'L · 專科分類重構（Taxonomy）' --state open
```

有程式變更時，從單一 Step 建立短期分支（例如 `l/t1-topic-registry`）；PR 使用 `Closes #N`。文件、ADR 與管理工作直接提交至 `main`。commit message 使用 English Conventional Commits，有 issue 時帶 `(#N)`。

## 資料權威與發布規則

- **單一內容權威**：`data/WRITER` 為 `postgres`；PostgreSQL `app` schema 是文獻、新聞、主題、留言與論壇的唯一權威來源（ADR-0021）。`data/papers.json` 與 `data/news.json` 僅作為本機／CI seed fixtures，不再接受正式寫入。
- **單一寫入端**：`guthub_api` 角色對內容表僅有唯讀權限；所有正式發布、標記已審與撤下均經由 content-owner 角色在交易鎖（`guthub-content-writer`）與 `app.publish_events` 冪等保護下執行。
- **Provenance Gate**：Paper Watch 自動發布須通過 `scripts/provenance.py`（完整 PubMed 摘要、數字逐字可溯源、`validate_data()`）；AI 新聞稿須通過 `newsroom/gate.py` 與 `scripts/news_writer.py` 結構檢查。
- **公開／私有隔離**：匿名作者對應、醫師驗證資料、個人主題／文獻訂閱與驗證會員論壇皆嚴格隔離於公開快取與搜尋引擎之外（ADR-0017、ADR-0022）。

## 本機開發

### 1. Python（Worker、Scripts 與 FastAPI）

需要 Python 3.12+（FastAPI 使用 `uv`，見 `apps/api/README.md`）：

```bash
# 根目錄 worker / scripts 測試與資料驗證
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt -r requirements-dev.txt

python scripts/validate.py --ci
python -m pytest tests/ -q

# FastAPI 檢查與測試
cd apps/api
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen pytest -q
```

### 2. Next.js 前端（`apps/web/`）

需要 Node.js 24 LTS。`apps/web/src/lib/api.generated.ts` 由 `contracts/openapi.yaml` 產生；修改 contract 後須執行 `npm run contract:generate` 並提交產物（CI `contract:check` 會驗證同步）。

```bash
cd apps/web
npm ci
npm run check       # contract 同步、TypeScript、ESLint、Prettier、Vitest
npm run dev         # http://localhost:3000

# production build 與 smoke test
npm run build
npm --prefix ../../tools ci
npm --prefix ../../tools exec playwright install chromium
npm run smoke
```

常用環境變數：

| 變數 | 用途 | 設定時機 |
| --- | --- | --- |
| `GUTHUB_API_URL` | FastAPI 位址（例如 `http://127.0.0.1:8000/api/v1`） | 執行時 |
| `GUTHUB_SITE_ORIGIN` | canonical、feed 與 sitemap 使用的網址（正式站 `https://guthub.tw`） | build 與執行時 |
| `GUTHUB_SITE_PUBLIC` | 設為 `1` 才允許搜尋引擎索引，並對 AI 未審頁面加 `noindex` | build 與執行時 |
| `GUTHUB_REVALIDATE_SECRET` | `POST /api/revalidate/` on-demand ISR 刷新密鑰（K3 #253） | 執行時 |
| `NEXT_PUBLIC_SUPABASE_URL`、`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`、`NEXT_PUBLIC_GUTHUB_API_URL` | 瀏覽器端登入與 API 呼叫設定 | build 時 |
| `NEXT_PUBLIC_AUTH_GOOGLE`、`NEXT_PUBLIC_PUSH_PUBLIC_KEY` | 選用：啟用 Google 登入或 Web Push 按鈕 | build 時 |

Feed GUID 固定使用 `tag:odafeng.github.io,2026:` 前綴，不會隨網域更動而造成訂閱者重複收到舊文。

## Repository 結構

| 路徑 | 用途 |
| --- | --- |
| `apps/web/` | Next.js App Router / TypeScript / React 前端（含自包含 CSS、字型與圖示） |
| `apps/api/` | FastAPI 服務與維護排程 jobs（`guthub_api.maintenance`） |
| `contracts/` | `openapi.yaml`（API contract）、`pipeline-migration.md`（及未來 `taxonomy.json`） |
| `supabase/` | Supabase PostgreSQL migrations（`app` schema）與設定 |
| `worker/` | Cloud Run worker 入口（`run.py`、`content_requests.py`、`Dockerfile`） |
| `scripts/` | Paper Watch、分類／摘要／新聞稿生成、健保／TFDA 監測與語意索引腳本 |
| `newsroom/` | AI 新聞稿數字來源查核 gate |
| `import_content.py`、`content_writer.py` | 資料庫匯入／匯出與寫入權切換工具 |
| `data/`、`docs/**/*.html` | 本機／CI seed fixtures、寫入旗標（`data/WRITER`）與歷史詳細證據頁 |
| `tests/`、`tools/` | Python pytest 與 Playwright browser／smoke／還原演練工具 |
| `.github/workflows/` | CI、staging／production 部署、待部署追蹤與排程 workflows |
| `docs/adr/`、`docs/plans/` | 架構決策紀錄（ADR）與產品技術規劃文件 |

## 架構決策（ADR）

| ADR | 內容 |
| --- | --- |
| [0013](docs/adr/0013-gated-auto-publish.md) | 有門檻的自動發布與人工審核 |
| [0015](docs/adr/0015-guthub-nextjs-product-scope.md) | GutHub 名稱、Next.js／React 方向與遷移範圍 |
| [0016](docs/adr/0016-api-data-cloud-boundaries.md) | API／worker、雲端服務分工、單一資料權威與切換 |
| [0017](docs/adr/0017-comments-and-anonymous-identity.md) | 登入、匿名留言、公開資料與管理權限 |
| [0018](docs/adr/0018-python-pipeline-and-adk.md) | Python 管線保留與 ADK 導入門檻 |
| [0019](docs/adr/0019-nextjs-offline-sync-and-client-search.md) | Next.js 離線快取與站內搜尋同步 |
| [0020](docs/adr/0020-browser-session-and-bearer-api.md) | 登入 session 僅存瀏覽器，API 僅收 Bearer token |
| [0021](docs/adr/0021-single-content-writer-and-cutover.md) | 單一內容寫入端、交易鎖與 PostgreSQL 正式切換 |
| [0022](docs/adr/0022-engagement-and-gated-forum.md) | 回訪機制（LINE、健保監測、語意搜尋）與驗證醫師論壇 |
| [0023](docs/adr/0023-web-push-through-the-api.md) | Web Push 訂閱走 API，新消息由排程 job 各推一次 |
| [0024](docs/adr/0024-staging-for-schema-and-sign-in.md) | Staging 作為 schema、認證與部署變更的正式前預演閘門 |
| [0025](docs/adr/0025-paper-summaries.md) | 文獻頁結構化繁中白話摘要 |
| [0026](docs/adr/0026-browse-by-drug.md) | 依藥物瀏覽試驗與實證演進 |
| [0027](docs/adr/0027-retire-static-site-and-read-postgres-directly.md) | 退役舊靜態網站管線，Paper Watch 直接讀取 PostgreSQL |
| [0028](docs/adr/0028-colorectal-surgery-scope-and-robotic-papers.md) | 擴大微創大腸直腸外科追蹤並啟用 `robotic-surgery` 論文自動發布 |
| [0029](docs/adr/0029-autonomous-paper-watch-self-repair.md) | Paper Watch 有界 AI self-repair 並停開常規審核 issues |
| [0030](docs/adr/0030-specialty-taxonomy-and-topic-registry.md) | 八大專科共用分類架構、Central Topic Registry 與向後相容遷移 |
| [0031](docs/adr/0031-event-centric-newsroom-and-intake-security.md) | 事件導向 Newsroom 架構、ChatGPT News Radar 安全邊界與發布治理 |

早期靜態站階段之歷史 ADR（`0001`–`0012`、`0014`）保留於 [`docs/adr/`](docs/adr/) 供查考。

## 維護者與授權

黃士峯（Shih-Feng Huang, MD），高雄榮民總醫院大腸直腸外科醫師。

[個人網站](https://shihfenghuang.com) · [GitHub](https://github.com/odafeng) · [ORCID](https://orcid.org/0000-0002-8037-4074)

目前 repository 未附 LICENSE 檔，程式授權需由維護者補齊確認。文獻內容的權利仍屬原作者與出版單位。
