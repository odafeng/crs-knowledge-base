# Seminar Hegemon

> 大腸直腸外科臨床決策知識庫 — 多頁實證更新站 + 7 個 AI Agent 自動文獻追蹤

[![PWA](https://img.shields.io/badge/PWA-offline--ready-1a365d)](https://web.dev/progressive-web-apps/)
[![Deploy](https://img.shields.io/badge/GitHub%20Pages-live-3182ce)](https://odafeng.github.io/crs-knowledge-base/)
[![CI](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml)
[![Paper Watch](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-38a169)](#授權)

**Live**：<https://odafeng.github.io/crs-knowledge-base/>

---

## 簡介

**Seminar Hegemon** 是一套面向**大腸直腸外科臨床醫師**的口袋型知識庫，搭載 **7 個 AI Agent 驅動的自動文獻追蹤系統**。

- 讓主治醫師在 **30 秒內**查到關鍵試驗數據
- **7 個 Topic-Specific AI Agent** 自動追蹤 PubMed + 主要期刊文獻（經 PubMed 查詢）
- 每個 agent 具備 **tool use + chain-of-thought** 能力，自主搜尋 PubMed、查閱 guideline、交叉比對既有文獻
- 高分文獻若所有數字都能在 PubMed 摘要逐字查證，自動發布並標示「未經人工審核」；其餘開 GitHub Issue 待審（ADR-0013），並 LINE 推播

> **臨床免責聲明**：本網站僅供醫學教育與臨床參考用途，**不構成醫療建議**。

---

## 功能特色

### 知識庫本體

- Python/Jinja2 產生首頁、消息、文獻、主題與訂閱頁；每頁都有獨立網址。
- 收錄 7 篇 AI 新聞稿，保留 AI 未審標示與 `noindex`。建置時會檢查稿件數字是否出現在對應文獻條目，仍需人工確認解讀。
- 搜尋消息與文獻，支援深色模式、字級調整及手機導覽。
- Service Worker 預先快取網站頁面與素材，首次完整載入後可離線閱讀與搜尋。
- 提供全部更新、新聞及各文獻主題的 RSS，以及 Atom、JSON Feed。
- 現有詳細證據內文整合進新版頁面，保留來源說明與限制。

### AI 自動更新系統（Paper Watch）

- **7 個 Topic-Specific AI Agent** — 每個主題有專屬 Claude agent，內建完整治療演進脈絡
- **Agentic Loop** — agent 可自主呼叫 6 個工具做多步推理（非單次 API call）
- **Chain-of-Thought** — adaptive thinking（effort high），推理摘要完整記錄在 CI logs
- **Cross-Paper Context** — 同批候選論文互相可見，支持相對判斷
- **Structured Output** — 透過 `submit_classification` tool 強制 JSON 輸出，不依賴 regex 解析
- **Conference Season Supplement** — 會議季自動搜尋 JCO/Ann Oncol/DCR meeting abstract supplements
- **Supplement Search** — 會議季自動搜尋 JCO/Ann Oncol/DCR meeting abstract supplements
- **LINE 推播** — 有新的重要文獻時即時通知
- **Data Validation** — CI 自動檢查 ID 重複、relation target、缺檔、欄位完整性

---

## 主題涵蓋（7 個 AI Agent）

每個主題由一個獨立的 AI agent 負責，各自擁有該領域的完整知識脈絡：

| # | 主題 | Agent 領域知識 | 文獻數 |
|---|---|---|---|
| 1 | **mCRC — BRAF V600E** | BEACON、BREAKWATER 全系列、ctDNA dynamics、NCCN | 8 |
| 2 | **mCRC — KRAS G12C** | CodeBreaK、KRYSTAL、divarasib+cetuximab、FAK 組合 | 8 |
| 3 | **mCRC — MSI-H / dMMR** | KEYNOTE-177、NICHE、dostarlimab / AZUR-1 non-op | 12 |
| 4 | **mCRC — HER2** | DESTINY-CRC、MOUNTAINEER、T-DXd | 5 |
| 5 | **mCRC — RAS-wt Anti-EGFR** | PARADIGM、sidedness、rechallenge | 9 |
| 6 | **mCRC — Agnostic** | fruquintinib/FRESCO、regorafenib、TAS-102+bev/SUNLIGHT | new |
| 7 | **Robotic Surgery** | REAL、ROLARR、TME/CME/anastomosis | 上線 |

### Agent 工具清單

| # | 工具 | 用途 |
|---|---|---|
| 1 | `search_pubmed` | 搜尋 PubMed（相關文獻、citing articles） |
| 2 | `fetch_paper_details` | 用 PMID 取得完整摘要 |
| 3 | `lookup_existing_papers` | 查閱 KB 既有文獻（判斷 relations） |
| 4 | `web_fetch` | 瀏覽 DOI 頁面（readability 智能提取） |
| 5 | `query_guidelines` | 搜尋 PubMed 上的 ASCO/ESMO/NCCN guideline 文章 |
| 6 | `submit_classification` | 提交結構化評分結果（強制 JSON） |

---

## 系統架構

```
┌─────────────────────────────────────────────────────────┐
│              GitHub Actions (4 Workflows)                │
├────────────────┬────────────────┬────────────────────────┤
│ Paper Watch    │ Refresh        │ Refresh Conference     │
│ Tue/Fri +      │ Guidelines     │ Dates                  │
│ conference     │ Monthly        │ Quarterly              │
│ daily          │                │                        │
└───────┬────────┴────────────────┴────────────────────────┘
        │
  ┌─────┼─────────────┐
  ▼     ▼             ▼
PubMed    Journal feeds
(+suppl)  (via PubMed)
        │
  deduplicate
        │
  7 AI Agents (agentic loop)
  ├─ [CoT] Extended thinking
  ├─ [Tool] search_pubmed / fetch_paper_details / ...
  ├─ Cross-paper batch context
  └─ [Submit] submit_classification
        │
  score ≥ 4 ──→ provenance gate（數字逐字比對摘要）
                 ├─ 通過 → 自動發布（AI 未審）+ LINE
                 └─ 未通過 → GitHub Issue（附原因）→ accepted label 一鍵發布
  parse fail ──→ [Review] Issue + parse-failed label
  評論類文章 ──→ 輕量分流 → 掛到既有試驗的「相關評論」
```

### AI 評分標準

| 分數 | 定義 | 動作 |
|---|---|---|
| **5** | Practice-changing | 過關卡自動發布，否則 Issue；LINE |
| **4** | High-impact | 過關卡自動發布，否則 Issue；LINE |
| **3** | Moderate | 忽略 |
| **2** | Low | 忽略 |
| **1** | Not relevant | 忽略 |

### 會議季掃描

| 會議 | 窗口 (±2w buffer) | 頻率 |
|---|---|---|
| ASCO GI | 1/5 ~ 2/15 | 每日 |
| ASCO Annual | 5/20 ~ 6/25 | 每日 |
| ESMO World GI | 6/25 ~ 7/25 | 每日 |
| ESMO Congress | 9/5 ~ 11/5 | 每日 |

日期每季自動從官網抓取更新。非會議季：每週二、五。

---

## 技術棧

### 前端

| 項目 | 選用 |
|---|---|
| 前端 | Python/Jinja2 產生靜態 HTML + CSS + Vanilla JS |
| 離線 | 建置時產生 precache 清單與內容版本；網路失敗時讀取快取 |
| 網址 | 多頁目錄路徑，例如 `mcrc/braf-v600e/`、`papers/beacon-2019/` |
| 部署 | CI 建置與測試後，將 `site/` 部署到原 GitHub Pages 網址 |

### 後端（Pipeline）

| 項目 | 選用 |
|---|---|
| AI | Claude Fable 5.2 + adaptive thinking + tool use + server-side refusal fallback |
| 文獻來源 | PubMed E-utilities（含 topic 查詢、期刊查詢、meeting abstract supplements）|
| Guideline | PubMed guideline article search |
| 通知 | LINE Messaging API |
| 網路 | exponential backoff retry (3x) |
| 驗證 | `validate.py`（CI 自動跑） |
| 測試 | pytest + Playwright E2E + axe-core |
| Topic 管理 | `topics.py` Enum（single source of truth） |

---

## 部署與設定

### GitHub Secrets

| Secret | 必要性 | 說明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | **必要** | Claude API key。[取得](https://console.anthropic.com/settings/keys) |
| `NCBI_API_KEY` | 選填 | PubMed rate limit 3→10 req/s。[申請](https://www.ncbi.nlm.nih.gov/account/settings/) |
| `LINE_CHANNEL_ACCESS_TOKEN` | 選填 | LINE 推播 channel token |
| `LINE_USER_ID` | 選填 | LINE 推播收件人 User ID（`U` 開頭） |

### LINE 推播設定

1. [LINE Developers Console](https://developers.line.biz/console/) 建立 Messaging API Channel
2. Issue long-lived channel access token
3. Basic settings 找到 User ID（`U` 開頭）
4. 加入 GitHub Secrets

---

## 本地開發

```bash
git clone https://github.com/odafeng/crs-knowledge-base.git
cd crs-knowledge-base

# Python 3.12+
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt -r requirements-site.txt

# 建置與預覽新版（請服務 site/，不要服務 repo 根目錄）
python build.py
python -m http.server 8000 --directory site  # http://localhost:8000

# 驗證 + Python 測試
python scripts/validate.py --ci
python -m pytest tests/ -v
python tools/check_links.py site

# Browser E2E、離線閱讀與 accessibility
cd tools
npm ci
npx playwright install chromium
npm test
npm run verify
cd ..

# Pipeline 設定
cp .env.example .env  # 填入 API keys

# Dry-run
cd scripts && python main.py --dry-run

# 手動觸發 (GitHub Actions)
gh workflow run paper-watch.yml
gh workflow run paper-watch.yml --field topic=mCRC-BRAF-V600E
```

---

## 新增證據文獻

### 自動（推薦）

Paper Watch 自動偵測 → AI agent 評分 → ≥4 分 → GitHub Issue + LINE 通知 → 你審核決定是否收錄。

### 手動

```
docs/<TopicSlug>/<FirstAuthor>_<Journal>_<Year>_<TrialName>[_<Subtopic>].html
```

1. 在 `docs/` 建立詳細證據 HTML，並於 `data/papers.json` 新增條目與 `file` 路徑。
2. 需要新聞稿時，手動加入 `data/news.json`，指定 `paperId` 並標記審核狀態。
3. 執行 `python build.py` 與測試。建置會套用新版版型，並自動更新離線快取。
4. 變更推送至 main 後，CI 驗證資料、執行測試並部署 `site/`。

---

## 新版來源與部署

| 路徑 | 用途 |
|---|---|
| `build.py`、`sitegen/` | 載入資料、產生頁面、Feed、metadata 與快取版本 |
| `templates/`、`static/` | Jinja2 版型、樣式、字型、圖示與瀏覽器腳本 |
| `data/papers.json`、`docs/` | 現有文獻資料與詳細證據內文 |
| `data/news.json` | 目前正式建置採用的 7 篇 AI 未審新聞稿 |
| `newsroom/gate.py` | 新聞稿的數字來源檢查，建置時強制執行 |
| `push/` | Web Push 金鑰、發送工具及訂閱資料表範本 |
| `tools/` | E2E、accessibility、連結與版面檢查工具 |
| `site/` | 建置產物，已加入 `.gitignore` |

新版直接取代原站，首頁與文獻頁都直接呈現內容，不產生 redirect。舊 hash 與 `docs/` 網址不再作為公開頁面；請改用新版網址。架構決策見 [ADR-0014](docs/adr/0014-generated-multipage-site.md)。

### Web Push 設定

網站在未設定推播時仍可閱讀、離線使用與訂閱 RSS。此次未建立訂閱後端，也未發送通知。

若要啟用，先建置支援 `push/schema.sql` 的訂閱後端，執行 `python -m push.keys` 產生 VAPID 金鑰，再於 GitHub repository variables 設定 `PUSH_PUBLIC_KEY`、`PUSH_API`、`PUSH_API_KEY`。CI 會將公開設定帶入建置；私鑰不可放進 variables 或網站產物。

發送工具需另外設定 `PUSH_SERVICE_KEY`、`VAPID_PRIVATE_KEY`、`VAPID_SUBJECT`：

```bash
python -m push.send --news data/news.json --id <新聞稿 id>
```

Web Push 尚未經實機驗證。Paper Watch 目前只發布文獻與評論，尚未自動產生新聞稿或發送 Web Push。

---

## Roadmap

- [ ] ASCO 2026 Annual Meeting 最新資料收錄
- [ ] 機器人手術 CME、TaTME 子主題
- [ ] 肛門手術章節
- [ ] 搜尋加入 fuzzy matching
- [ ] Token cost monitoring

---

## 作者

**黃士峯（Shih-Feng Huang, MD）**
Colorectal Surgeon, Kaohsiung Veterans General Hospital

- [shihfenghuang.com](https://shihfenghuang.com)
- [@odafeng](https://github.com/odafeng)
- ORCID: [0000-0002-8037-4074](https://orcid.org/0000-0002-8037-4074)

---

## 授權

本專案以 [MIT License](LICENSE) 釋出。

各篇 evidence pages 內容為原始文獻之摘要與整理，**所引用之臨床試驗數據與圖表智慧財產權屬於原作者與原出版單位**；本網站使用屬合理使用（fair use）範圍之教育用途。
