# GutHub

大腸直腸外科實證知識庫，規劃加入專業討論與匿名留言。原名 **Seminar Hegemon**。

GutHub 是這次改版的產品名稱。正式站仍使用 Python/Jinja2 靜態網站與 Paper Watch；`apps/web/` 已建立 **Next.js + TypeScript + React** 基礎，尚未接入完整閱讀頁面。FastAPI、使用者登入與留言尚未實作，雲端供應商與匿名政策仍待決定。

[CI](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml) · [Paper Watch](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml) · [Jobs / milestones](https://github.com/odafeng/crs-knowledge-base/milestones) · [Issues](https://github.com/odafeng/crs-knowledge-base/issues)

> 內容供醫療專業人員教育與臨床參考，不構成醫療建議。AI 整理與新聞稿的查核範圍有限，臨床判斷請回到原始文獻及現行指引。

## 目前能做什麼

- 依 biomarker 與手術主題閱讀文獻、詳細證據、治療方案及核准／給付狀態，保留資料來源和複查日期。
- 閱讀 AI 新聞稿；未經人工審核的內容有標示，並使用 `noindex`。
- 搜尋文獻與消息，調整深色模式和字級；首次完整載入後，可離線閱讀公開內容與搜尋。
- 訂閱 RSS、Atom 或 JSON Feed。
- 由七個主題的 Python agents 掃描 PubMed。通過 provenance gate 的條目標為 AI 未審；未通過的送 GitHub Issue，供人工決定是否收錄。

讀者留言將使用獨立的 `comments` 模型。現有文獻中的 `commentary` 是期刊社論、來信等研究評論，兩者不可混用。

## 部署現況

目前公開網址是 **<https://odafeng.github.io/crs-knowledge-base/>**，平台為 GitHub Pages。

Pages 使用 GitHub Actions 發布通過測試的 `site/` artifact，停用 `main` 根目錄的另一條建置路徑。部署前會檢查 Pages 的 `build_type` 為 `workflow`；公開的 [`build-info.json`](https://odafeng.github.io/crs-knowledge-base/build-info.json) 記錄該產物的 commit，供部署後核對版本。修復與驗證紀錄見 **[A4 #56](https://github.com/odafeng/crs-knowledge-base/issues/56)**。

目前的 `ci.yml` 設計是：驗證資料 → pytest → 建置 `site/` → 連結、E2E 與 accessibility 檢查 → 部署同一份 artifact。未來 Next.js 與 API 的 hosting 由 [A1 #53](https://github.com/odafeng/crs-knowledge-base/issues/53) 選定，正式切換由 [F4 #79](https://github.com/odafeng/crs-knowledge-base/issues/79) 驗收。

repository 目前仍叫 `odafeng/crs-knowledge-base`。顯示名稱、repository 名稱和正式網域是不同變更，後兩者依 [A3 #55](https://github.com/odafeng/crs-knowledge-base/issues/55) 決定。

## 建置工作如何追蹤

**Jobs 使用 milestones，Steps 使用 issues。** 依賴、驗收條件、負責人與討論放在 issue；README 只提供入口，不另維護待辦狀態。

| Job | 工作範圍 | GitHub milestone |
|---|---|---|
| A | 決策、現站發布修復、README 與 ADR | [GutHub 決策與上線基線](https://github.com/odafeng/crs-knowledge-base/milestone/1) |
| B | 資料／API contract、FastAPI、schema、權限與內容匯入 | [資料模型與 API](https://github.com/odafeng/crs-knowledge-base/milestone/2) |
| C | Next.js 閱讀頁面、搜尋、公開內容離線與品牌 | [Next.js 閱讀介面](https://github.com/odafeng/crs-knowledge-base/milestone/3) |
| D | 登入、署名／匿名留言、防濫用與檢舉審核 | [身分與留言](https://github.com/odafeng/crs-knowledge-base/milestone/4) |
| E | Paper Watch 的發布／撤下、排程與 ADK 評估 | [Paper Watch 遷移](https://github.com/odafeng/crs-knowledge-base/milestone/5) |
| F | 雲端環境、staging、還原演練與正式切換 | [環境、驗收與正式切換](https://github.com/odafeng/crs-knowledge-base/milestone/6) |

開始工作前，先讀對應 milestone 的 open issues。`[me]` 是 agent 可執行的工作；`[wait]` 需先完成列出的依賴；`[you]` 是維護者需決定或提供資源的事項。新建的規劃 issues 只使用 `blocked`、`needs-decision` 等狀態 labels；既有文獻管線的分類 labels 維持原用途。

```bash
gh issue list --repo odafeng/crs-knowledge-base --milestone 'A · GutHub 決策與上線基線' --state open
```

有程式變更時，從單一 Step 建立短期分支，例如 `c/c1-nextjs-foundation`；PR 使用 `Closes #N`。文件、決策與管理工作不預建分支。commit message 使用 English Conventional Commits，有 issue 時帶 `(#N)`。commit、push、PR 與 production 切換都依當次授權執行。

## 目標架構與待決策範圍

前端使用 Next.js、TypeScript、React。Python API 與 worker 承接目前的文獻處理邏輯；一般留言請求與長時間文獻掃描分開執行。供應商仍有兩套候選：

| 責任 | 建議起步方案 | 全 Google Cloud 候選 |
|---|---|---|
| Next.js 執行環境 | Vercel 等支援 Next.js server 的 hosting | Firebase App Hosting |
| 使用者登入 | Supabase Auth | Firebase Auth |
| PostgreSQL | Supabase PostgreSQL | Cloud SQL PostgreSQL |
| 檔案 | Supabase Storage | Cloud Storage |
| Python API／worker | FastAPI／既有 Python 任務，按需部署 Cloud Run | FastAPI／Cloud Run 與排程任務 |
| Agent framework | 先保留既有 agents，另評估 ADK | 同樣可先保留或另評估 ADK |

這張表是規劃選項，不代表雲端資源已建立。ADK 的決定與資料庫供應商分開，不是網站及留言上線的前提。

匿名政策依 [A2 #54](https://github.com/odafeng/crs-knowledge-base/issues/54) 決定。建議第一版先登入，再選署名或對其他讀者匿名；若同時開放免註冊留言，需加入匿名 session 的限速、驗證與管理方式。匿名作者對應不能只靠前端藏起來，公開 API、Data API、Realtime 及快取都必須隔離。

## 資料與發布規則

目前以 `data/papers.json`、`data/news.json` 與 `docs/**/*.html` 為內容來源；`site/` 是可重建產物。資料庫遷移前，這些來源仍是權威資料。

切換後由選定的 PostgreSQL 成為內容與留言的單一權威來源。匯入需要 dry-run、數量／雜湊 manifest、重跑去重及回復方式；切換時先停舊 writer，再啟用新 writer。JSON 若繼續保留，作單向 export，不能同時讓 git 與資料庫接受獨立寫入。

文獻 ID、DOI、關聯、來源、審核狀態及詳細證據必須保留。研究 commentary、讀者 comments、AI 新聞稿與來源證據各有不同用途；讀者留言不會自動成為文獻來源或進入發布管線。

目前的發布規則見 [ADR-0013](docs/adr/0013-gated-auto-publish.md)：

1. PubMed／期刊候選文獻先去重，再由 topic agent 分類與產生結構化資料。
2. 通過程式檢查的來源、數字與研究設計才可自動發布，並標示 AI 未審；其他項目開 Issue。
3. 人工接受由 `accepted` label workflow 處理；撤下使用 `Unpublish` workflow。人工整理內容不能任意用 bot 流程刪除。
4. provenance gate 不能保證臨床解讀正確。更換儲存、API 或 agent framework 時，保留現有 gate 與回歸案例。

新聞稿另外由 `newsroom/gate.py` 比對數字是否出現在對應條目。這項檢查不保證數字的組別、指標或文字解讀正確。Paper Watch 目前尚未自動寫新聞稿，也未串接 Web Push 發送。

## 本機開發：目前的 v3 網站

需要 Python 3.12+；browser checks 另需 Node.js 與 Chromium。以下指令操作目前正式站使用的靜態網站。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt -r requirements-site.txt -r requirements-dev.txt

# 建置與預覽；請服務 site/，不要服務 repo 根目錄
python build.py
python -m http.server 8000 --directory site
```

預覽網址：<http://localhost:8000/>。

```bash
# 資料、Python 與內部連結
python scripts/validate.py --ci
python -m pytest tests/ -q
python tools/check_links.py site

# Browser E2E、離線、accessibility 與版面
cd tools
npm ci
npx playwright install chromium
npm test
npm run verify
```

## 本機開發：Next.js 前端

使用 Node.js 24 LTS。`apps/web/` 是遷移中的閱讀介面，沿用 v3 的 CSS tokens 與本地字型；首頁的「閱讀文獻」連到現行正式站。正式部署仍發布 `site/`，不會部署這個骨架。

```bash
cd apps/web
npm ci
npm run check       # contract 同步、TypeScript、ESLint、Prettier、Vitest
npm run dev         # http://localhost:3000

# production build 與 dev/production 瀏覽器啟動測試
npm run build
npm --prefix ../../tools ci
npm --prefix ../../tools exec playwright install chromium
npm run smoke
```

`src/lib/api.generated.ts` 由 `contracts/openapi.yaml` 產生。修改 contract 後執行 `npm run contract:generate` 並提交產物；CI 的 `contract:check` 會拒絕過期 types。`getPaper` 可指定 API origin 或注入 fixture fetcher，目前尚無 API server。`/api/health` 只供前端啟動檢查。

Next.js CI 會執行 checks、runtime dependency audit、build 與 Playwright 測試。ESLint 暫用 9.x，以符合 Next.js 所帶 plugins 的 peer dependencies；開發依賴中仍有上游 `minimatch` 的 moderate advisory，runtime audit 另行檢查，不以跨 major override 掩蓋相容性問題。

API 的 Ruff、Pyright、pytest 與啟動 smoke 由 [B2 #59](https://github.com/odafeng/crs-knowledge-base/issues/59) 建立。正式切換前，另需權限矩陣、資料匯入與還原驗證。

## Paper Watch 與設定

目前 `scripts/config.py` 管理模型、門檻與資料路徑，`scripts/topics.py` 管理主題，`scripts/queries.json` 管理搜尋與會議季窗口。一般掃描每週二、五；會議季另有每日排程。內容複查與會議日期更新有獨立 workflows。

| 設定 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 現有 Python agents 的必要設定 |
| `NCBI_API_KEY` | PubMed API 的選填設定 |
| `GH_TOKEN`／`GITHUB_TOKEN` | 發布、審核 issues 與 workflow 操作；Actions 由環境提供 |
| `LINE_CHANNEL_ACCESS_TOKEN`、`LINE_USER_ID` | 選填 LINE 通知 |
| `PUSH_PUBLIC_KEY`、`PUSH_API`、`PUSH_API_KEY` | 選填 Web Push 公開建置設定 |
| `PUSH_SERVICE_KEY`、`VAPID_PRIVATE_KEY`、`VAPID_SUBJECT` | Web Push 發送端設定，私鑰不可進前端 |

祕密放 CI／平台 secret store，不貼在 README 或 issues。本機程式從環境讀取設定；複製 `.env.example` 後，需由自己的 shell／開發工具載入，不能假設程式會自動讀取 `.env`。

```bash
# 以下均在 repository 根目錄執行
python scripts/main.py --dry-run
python scripts/main.py --dry-run --topic mCRC-BRAF-V600E

# 手動觸發會產生外部操作的 workflow，先確認使用目的與設定
gh workflow run paper-watch.yml --field dry_run=true
```

Web Push 的程式與 SQL 範本放在 `push/`，目前不等於已建立 Supabase Auth、留言資料庫或訂閱後端。尚未設定推播時，網站仍能閱讀與訂閱 Feed；實機推播驗證另待安排。

手動新增內容時，在 `data/papers.json` 加入文獻條目與詳細 HTML 的 `file` 路徑；新聞稿加入 `data/news.json` 並指定 `paperId`、審核狀態。執行資料驗證、建置與測試後，再依授權提交。

## Repository 結構

| 路徑 | 目前用途 |
|---|---|
| `build.py`、`sitegen/` | 載入內容、產生頁面、Feed、metadata 與離線快取版本 |
| `templates/`、`static/` | 現行 Jinja2 版型、CSS、瀏覽器腳本、字型與圖示 |
| `apps/web/` | 遷移中的 Next.js App Router／TypeScript／React 前端，尚未正式部署 |
| `data/` | 文獻、新聞及 DOI／PMID 追蹤資料 |
| `docs/**/*.html` | 詳細證據內容來源，不作為新版的獨立公開頁面 |
| `scripts/` | PubMed、分類、來源查核、發布／撤下及維護任務 |
| `newsroom/` | AI 新聞稿數字來源檢查 |
| `push/` | Web Push 金鑰、發送工具與訂閱資料表範本 |
| `tests/`、`tools/` | pytest 與 browser／連結／版面檢查 |
| `contracts/` | 規劃中的 OpenAPI contract 與來源／隱私邊界驗證，目前尚無 API server |
| `.github/workflows/` | CI、Paper Watch、人工接受、撤下及維護排程 |
| `docs/adr/` | 架構決策與取捨 |
| `site/` | 建置產物，已 gitignore |

## 架構決策

| ADR | 內容 |
|---|---|
| [0013](docs/adr/0013-gated-auto-publish.md) | 現行有門檻的自動發布與人工審核 |
| [0014](docs/adr/0014-generated-multipage-site.md) | 現行 Python/Jinja2 多頁網站 |
| [0015](docs/adr/0015-guthub-nextjs-product-scope.md) | GutHub 名稱、Next.js／React 方向與遷移範圍 |
| [0016](docs/adr/0016-api-data-cloud-boundaries.md) | API／worker、雲端候選、單一資料權威與切換 |
| [0017](docs/adr/0017-comments-and-anonymous-identity.md) | 登入、匿名留言、公開資料與管理權限 |
| [0018](docs/adr/0018-python-pipeline-and-adk.md) | Python 管線保留與 ADK 導入門檻 |

`Accepted` 表示已採用的方向，不代表功能已完成；實作與驗收狀態以對應 issues 為準。`Proposed` 的選項需由決策 issue 確認後再實作。

## 維護者與授權

黃士峯（Shih-Feng Huang, MD），高雄榮民總醫院大腸直腸外科醫師。

[個人網站](https://shihfenghuang.com) · [GitHub](https://github.com/odafeng) · [ORCID](https://orcid.org/0000-0002-8037-4074)

目前 repository 未附 LICENSE 檔，程式授權需由維護者補齊確認。文獻內容的權利仍屬原作者與出版單位；改名、搬站或使用 Storage 不會取得原始全文的再散布權。
