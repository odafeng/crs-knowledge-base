# CRS Knowledge Base

> 大腸直腸外科臨床決策知識庫 — PWA + 7 個 AI Agent 自動文獻追蹤

[![PWA](https://img.shields.io/badge/PWA-offline--ready-1a365d)](https://web.dev/progressive-web-apps/)
[![Deploy](https://img.shields.io/badge/GitHub%20Pages-live-3182ce)](https://odafeng.github.io/crs-knowledge-base/)
[![CI](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml)
[![Paper Watch](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml)
[![Tests](https://img.shields.io/badge/tests-63%20passed-38a169)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-38a169)](#授權)

**Live**：<https://odafeng.github.io/crs-knowledge-base/>

---

## 簡介

**CRS Knowledge Base** 是一套面向**大腸直腸外科臨床醫師**的口袋型知識庫，搭載 **7 個 AI Agent 驅動的自動文獻追蹤系統**。

- 讓主治醫師在 **30 秒內**查到關鍵試驗數據
- **8 個 Topic-Specific AI Agent** 自動追蹤 PubMed + 主要期刊文獻（經 PubMed 查詢）
- 每個 agent 具備 **tool use + chain-of-thought** 能力，自主搜尋 PubMed、查閱 guideline、交叉比對既有文獻
- 高分文獻自動建立 GitHub Issue + LINE 推播通知

> **臨床免責聲明**：本網站僅供醫學教育與臨床參考用途，**不構成醫療建議**。

---

## 功能特色

### 知識庫本體

- **行動優先設計** — 單欄 + sticky header，手術衣口袋掏出來就查
- **完全離線可用** — Service Worker precache 所有頁面（含 docs），醫院 Wi-Fi 死角也能用
- **Deep Link** — hash routing（如 `#braf`、`#msih`），可直接分享特定主題連結
- **可加入主畫面** — PWA manifest，行為近似原生 App
- **生物標記導向** — 以 biomarker 為主軸的 mCRC 治療決策樹
- **試驗時間軸 + 互動式柱狀圖** — 療效數據視覺比較

### AI 自動更新系統（Paper Watch）

- **7 個 Topic-Specific AI Agent** — 每個主題有專屬 Claude agent，內建完整治療演進脈絡
- **Agentic Loop** — agent 可自主呼叫 6 個工具做多步推理（非單次 API call）
- **Chain-of-Thought** — extended thinking，推理過程完整記錄在 CI logs
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
| 1 | **mCRC — BRAF V600E** | BEACON、BREAKWATER 全系列、ctDNA dynamics | 7 |
| 2 | **mCRC — KRAS G12C** | CodeBreaK、KRYSTAL、divarasib+cetuximab | 7 |
| 3 | **mCRC — MSI-H / dMMR** | KEYNOTE-177、NICHE、dostarlimab non-op | 8 |
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
  score ≥ 4 ──→ GitHub Issue + LINE 推播
  parse fail ──→ [Review] Issue + parse-failed label
```

### AI 評分標準

| 分數 | 定義 | 動作 |
|---|---|---|
| **5** | Practice-changing | Issue + LINE |
| **4** | High-impact | Issue + LINE |
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
| 前端 | 原生 HTML5 + CSS3 + Vanilla JS（單檔 SPA） |
| 離線 | Service Worker v12（precache all docs，只 cache GET + res.ok） |
| 路由 | Hash-based deep link（`#braf`, `#msih`） |
| 部署 | GitHub Pages |

### 後端（Pipeline）

| 項目 | 選用 |
|---|---|
| AI | Claude Sonnet 4.6 + extended thinking + tool use |
| 文獻來源 | PubMed E-utilities（含 topic 查詢、期刊查詢、meeting abstract supplements）|
| Guideline | PubMed guideline article search |
| 通知 | LINE Messaging API |
| 網路 | exponential backoff retry (3x) |
| 驗證 | `validate.py`（CI 自動跑） |
| 測試 | pytest（71 tests） |
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

# 知識庫前端
python3 -m http.server 8000  # http://localhost:8000

# Pipeline
cp .env.example .env  # 填入 API keys
pip install -r scripts/requirements.txt

# 驗證 + 測試
python scripts/validate.py
python -m pytest tests/ -v

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

1. 建立 HTML 證據頁面（複製既有檔案改寫）
2. 在 `index.html` 對應的 `*_PAPERS` array 新增 JS 物件
3. `sw.js` CACHE_NAME 版本號 +1，precache 列表加入新檔
4. Push → CI validate + test → GitHub Pages 部署

---

## Roadmap

- [ ] 為 generic-CRS 和 robotic-surgery 加入 JS paper arrays + 前端頁面
- [ ] ASCO 2026 Annual Meeting 最新資料收錄
- [ ] 機器人手術 CME、TaTME 子主題
- [ ] 肛門手術章節
- [ ] Client-side fuzzy search
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
