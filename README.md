# CRS Knowledge Base

> 大腸直腸外科臨床決策知識庫 — 行動端 Progressive Web App + AI 自動更新

[![PWA](https://img.shields.io/badge/PWA-ready-1a365d)](https://web.dev/progressive-web-apps/)
[![Deploy](https://img.shields.io/badge/GitHub%20Pages-live-3182ce)](https://odafeng.github.io/crs-knowledge-base/)
[![CI](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/ci.yml)
[![Paper Watch](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml/badge.svg)](https://github.com/odafeng/crs-knowledge-base/actions/workflows/paper-watch.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-38a169)](#授權)

**Live**：<https://odafeng.github.io/crs-knowledge-base/>

---

## 簡介

**CRS Knowledge Base** 是一套面向**大腸直腸外科臨床醫師**的口袋型知識庫，搭載 **AI 驅動的自動文獻追蹤系統**。

設計目標：

- 讓主治醫師、總醫師、住院醫師在 **30 秒內**查到關鍵試驗數據
- **自動追蹤** ESMO、ASCO、主要期刊的最新研究結果
- **零人工介入**——新的 practice-changing 文獻自動出現在知識庫中

> **臨床免責聲明**：本網站僅供醫學教育與臨床參考用途，**不構成醫療建議**。所有臨床決策仍應由具執照之醫師依個別病人狀況綜合判斷。

---

## 功能特色

### 知識庫本體

- **行動優先設計** — 單欄 + sticky header，手術衣口袋掏出來就查
- **完全離線可用** — Service Worker（network-first）快取，醫院 Wi-Fi 死角也能用
- **可加入主畫面** — PWA manifest，行為近似原生 App
- **生物標記導向** — 以 biomarker 為主軸的 mCRC 治療決策樹
- **試驗時間軸視覺化** — landmark trials 以 timeline + 互動式柱狀圖呈現療效演進
- **每篇證據獨立頁面** — 每個 trial 一個 HTML，方便引用、轉貼、列印

### AI 自動更新系統（Paper Watch）

- **PubMed 定時掃描** — 每週二、五自動搜尋 6 個主題的最新文獻
- **會議季加密掃描** — ASCO、ESMO、ASCO GI、WCGC 期間每日掃描
- **6 個 Topic-Specific AI Sub-Agents** — 每個主題有專屬的 Claude 子代理，內建完整治療演進脈絡
- **自動部署** — 高分文獻自動建立 PR 並 merge，網頁即時更新
- **LINE 推播通知** — 有新的重要文獻時即時通知

---

## 主題涵蓋（6 個 AI Sub-Agent）

每個主題由一個獨立的 AI sub-agent 負責，各自擁有該領域的完整知識脈絡：

| # | 主題 | Sub-Agent 領域知識 | 狀態 |
|---|---|---|---|
| 1 | **mCRC — BRAF V600E** | BEACON 2019-2021、BREAKWATER 2025-2026、ctDNA dynamics、FOLFIRI cohort | ✅ 7 篇 |
| 2 | **mCRC — KRAS G12C** | CodeBreaK 101/300、KRYSTAL-1、divarasib+cetuximab、G12C 抑制劑+anti-EGFR 協同 | ✅ 7 篇 |
| 3 | **mCRC — MSI-H / dMMR** | KEYNOTE-177、CheckMate 142、NICHE/NICHE-2、dostarlimab non-operative management | ✅ 8 篇 |
| 4 | **mCRC — HER2 Amplification** | MyPathway、DESTINY-CRC01/02、MOUNTAINEER、T-DXd 對 RAS-mut 有效 | ✅ 5 篇 |
| 5 | **mCRC — RAS-wt Anti-EGFR** | FIRE-3、PARADIGM、sidedness、VALENTINO/PanaMa maintenance、CHRONOS rechallenge | ✅ 9 篇 |
| 6 | **Robotic Surgery** | ROLARR、COLRAR、REAL trial、TME/CME/anastomosis | ✅ 上線 |

### Sub-Agent 如何運作

每篇新候選文獻會被送到**對應主題的專屬 AI agent**。每個 agent 的 system prompt 包含：

1. **完整治療演進脈絡** — 該領域所有關鍵試驗的時間線與轉折點
2. **既有文獻的結構化資料** — 直接從 `index.html` 提取的 JS paper objects
3. **里程碑類型指引** — 指導 AI 判斷新結果屬於哪種突破（如「首個達 OS 主要終點的 Phase 3」）
4. **評分標準** — 1-5 分制，只有 ≥4 分才會觸發自動更新

這讓 AI 不只是「這篇文章相不相關」，而是能回答「**這篇文章在這個領域的治療演進中代表什麼意義**」。

---

## 系統架構

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub Actions (Cron)                 │
│              Tue/Fri + 會議季每日自動觸發                   │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ PubMed   │  │ RSS      │  │ ASCO/    │
   │ E-utils  │  │ Feeds    │  │ ESMO     │
   │ (14 天)  │  │ (8 期刊) │  │ Scrapers │
   └────┬─────┘  └────┬─────┘  └────┬─────┘
        └──────────────┼─────────────┘
                       ▼
              ┌────────────────┐
              │   去重 + 合併   │ ← tracked-dois.json
              └────────┬───────┘
                       ▼
        ┌──────────────────────────────┐
        │  6 個 Topic-Specific         │
        │  Claude Sub-Agents           │
        │  (claude-sonnet-4-6)         │
        │                              │
        │  每個 agent 擁有：            │
        │  • 治療演進完整脈絡           │
        │  • 既有文獻 JS objects        │
        │  • 里程碑判斷指引             │
        │                              │
        │  輸出：                       │
        │  • 相關性評分 (1-5)           │
        │  • 繁體中文脈絡分析           │
        │  • JS 物件草稿               │
        │  • HTML 頁面草稿             │
        └──────────┬───────────────────┘
                   │
           Score ≥ 4 ?
            │      │
           Yes     No → 忽略
            │
            ▼
   ┌────────────────────┐
   │ Auto-PR + Merge    │
   │                    │
   │ 1. git branch      │
   │ 2. Claude 生成 HTML│
   │ 3. 插入 JS object  │
   │ 4. PR → auto-merge │
   └────────┬───────────┘
            │
            ▼
   ┌────────────────────┐
   │ LINE 推播通知       │ → 你的手機
   └────────────────────┘
            │
            ▼
   ┌────────────────────┐
   │ GitHub Pages 部署   │ → 網頁即時更新
   └────────────────────┘
```

### AI 評分標準

| 分數 | 定義 | 觸發動作 |
|---|---|---|
| **5** | Practice-changing — 改變治療標準 | Auto-PR + merge + LINE |
| **4** | High-impact — 重要更新 | Auto-PR + merge + LINE |
| **3** | Moderate — 有參考價值 | 忽略 |
| **2** | Low — 重複性結果 | 忽略 |
| **1** | Not relevant | 忽略 |

### 會議季感知排程

| 會議 | 時間 | 掃描頻率 |
|---|---|---|
| ASCO GI | 1 月中 ~ 2 月初 | 每日 |
| ASCO Annual | 5 月底 ~ 6 月中 | 每日 |
| ESMO World GI (WCGC) | 7 月上旬 | 每日 |
| ESMO Congress | 9 月中 ~ 10 月底 | 每日 |
| 非會議季 | — | 每週二、五 |

---

## 技術棧

### 前端（知識庫本體）

| 項目 | 選用 |
|---|---|
| 前端 | 原生 HTML5 + CSS3 + Vanilla JS（單檔 SPA） |
| 樣式 | CSS variables（無框架） |
| 離線 | Service Worker v11，network-first 策略 |
| 安裝 | Web App Manifest（standalone display） |
| 部署 | GitHub Pages |
| 字型 | system font stack + Noto Sans TC |

### 後端（Paper Watch Pipeline）

| 項目 | 選用 |
|---|---|
| 語言 | Python 3.12（標準庫為主） |
| AI | Claude Sonnet 4.6 via Anthropic API |
| 文獻來源 | PubMed E-utilities + RSS + ASCO/ESMO |
| 通知 | LINE Messaging API |
| CI/CD | GitHub Actions |
| 測試 | pytest（54 tests） |

---

## 專案結構

```
crs-knowledge-base/
├── index.html                  # 單檔 SPA（含 6 組 paper arrays）
├── sw.js                       # Service Worker
├── manifest.json               # PWA manifest
├── icons/                      # PWA 圖標
│
├── docs/                       # 證據文獻 HTML 頁面
│   └── mCRC-BRAF-V600E/        # 7 篇（BEACON + BREAKWATER 系列）
│       ├── Kopetz_NEJM_2019_BEACON.html
│       ├── Tabernero_JCO_2021_BEACON.html
│       └── ...
│
├── scripts/                    # Paper Watch Pipeline
│   ├── config.py               # 環境變數 + 路徑常數
│   ├── queries.json            # 6 主題的 PubMed query + RSS + 會議關鍵字
│   ├── fetch_pubmed.py         # Layer 1a: PubMed E-utilities
│   ├── fetch_rss.py            # Layer 1b: RSS feed 解析
│   ├── fetch_conferences.py    # Layer 1c: ASCO/ESMO 爬蟲
│   ├── topic_agents.py         # 6 個 topic-specific sub-agent prompts
│   ├── classify.py             # Layer 2: Claude API 分類
│   ├── create_pr.py            # Layer 3: Auto-PR + auto-merge
│   ├── create_issues.py        # GitHub Issue 建立（備用）
│   ├── notify_line.py          # LINE 推播通知
│   ├── main.py                 # Pipeline 統一入口
│   ├── requirements.txt        # anthropic, pytest
│   └── templates/
│       └── evidence.html       # HTML 頁面模板
│
├── data/
│   ├── tracked-dois.json       # 已追蹤 DOI（去重用）
│   └── tracked-abstracts.json  # 已追蹤會議 abstract
│
├── tests/                      # 54 個 pytest 測試
│   ├── conftest.py
│   ├── test_fetch_pubmed.py
│   ├── test_fetch_rss.py
│   ├── test_classify.py
│   ├── test_create_pr.py
│   ├── test_create_issues.py
│   ├── test_notify_line.py
│   ├── test_topic_agents.py
│   └── test_main.py
│
├── .github/workflows/
│   ├── ci.yml                  # CI: pytest → GitHub Pages 部署
│   └── paper-watch.yml         # Paper Watch: 定時文獻掃描
│
├── .env.example                # 環境變數模板
└── .gitignore
```

---

## 部署與設定

### 1. GitHub Pages（知識庫前端）

Push 到 `main` branch 即自動部署。CI workflow 會先跑 pytest，通過後部署到 GitHub Pages。

### 2. Paper Watch Pipeline（AI 自動更新）

Pipeline 完全運行於 **GitHub Actions**，不需要額外的伺服器。

#### 必要的 GitHub Secrets

在 repo 的 **Settings → Secrets and variables → Actions** 設定：

| Secret | 必要性 | 說明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | **必要** | Claude API key，用於 AI 分類和 HTML 生成。[取得](https://console.anthropic.com/settings/keys) |
| `NCBI_API_KEY` | 選填 | 提高 PubMed rate limit（3/s → 10/s）。[申請方式](#ncbi-api-key-申請) |
| `LINE_CHANNEL_ACCESS_TOKEN` | 選填 | LINE 推播通知的 channel token |
| `LINE_USER_ID` | 選填 | LINE 推播的收件人 User ID（`U` 開頭） |

#### 月成本估算

| 項目 | 費用 |
|---|---|
| PubMed API | 免費 |
| Claude API | < $2 USD/月（每次約 5-20 篇 × 2 次/週） |
| GitHub Actions | 免費額度內 |
| LINE Messaging API | 免費（500 則/月） |

### 3. LINE 推播通知設定

1. 前往 [LINE Developers Console](https://developers.line.biz/console/)
2. 建立 Provider → 建立 **Messaging API Channel**
3. **Messaging API** tab → Issue 一個 long-lived **channel access token**
4. **Basic settings** tab → 最下方找到 **Your user ID**（`U` 開頭）
5. 將兩者加入 GitHub Secrets

### 4. NCBI API Key 申請

1. 前往 [NCBI 帳號頁面](https://www.ncbi.nlm.nih.gov/account/) 登入或註冊
2. 進入 [Settings](https://www.ncbi.nlm.nih.gov/account/settings/)
3. 找到 **API Key Management** → **Create an API Key**
4. 複製產生的 key，加入 GitHub Secrets 的 `NCBI_API_KEY`

---

## 本地開發

### 知識庫前端

```bash
git clone https://github.com/odafeng/crs-knowledge-base.git
cd crs-knowledge-base
python3 -m http.server 8000
# 開啟 http://localhost:8000
```

### Paper Watch Pipeline

```bash
# 安裝依賴
pip install -r scripts/requirements.txt

# 設定環境變數
cp .env.example .env
# 編輯 .env 填入 API keys

# Dry-run 測試（不建 PR、不推播）
cd scripts
python main.py --dry-run

# 單一主題測試
python main.py --topic mCRC-BRAF-V600E --dry-run

# 跑測試
cd ..
python -m pytest tests/ -v
```

### 手動觸發 Paper Watch（GitHub Actions）

```bash
# 完整掃描
gh workflow run paper-watch.yml

# 指定主題
gh workflow run paper-watch.yml --field topic=mCRC-BRAF-V600E

# Dry-run（不建 PR）
gh workflow run paper-watch.yml --field dry_run=true
```

---

## 新增證據文獻

### 自動新增（推薦）

Paper Watch pipeline 會自動偵測、評分、生成 HTML、更新 `index.html`、merge 並部署。你只需收到 LINE 通知後確認即可。

### 手動新增

#### 命名規則

```
docs/<TopicSlug>/<FirstAuthor>_<Journal>_<Year>_<TrialName>[_<Subtopic>].html
```

例：
- `Kopetz_NEJM_2019_BEACON.html`
- `Kopetz_ESMO_2025_BREAKWATER_ctDNA.html`

#### 步驟

1. 在 `docs/<TopicSlug>/` 下建立新的 `.html` 檔（可複製既有檔案改寫）
2. 每篇至少包含：`<title>`、`<h1>`、`.meta` 區塊、Abstract、Key Results 表格、Conclusions
3. 在 `index.html` 對應的 `*_PAPERS` array 新增 JS 物件
4. 將 `sw.js` 的 `CACHE_NAME` 版本號 +1
5. Push 到 `main` → CI 跑測試 → GitHub Pages 自動部署

---

## Roadmap

- [ ] 補齊 mCRC 各 biomarker 章節的 evidence pages（docs/ HTML 檔案）
- [ ] 機器人手術加上 CME、TaTME、單孔手術子主題
- [ ] 肛門手術章節（痔瘡、廔管、肛裂）
- [ ] 加入 client-side fuzzy search
- [ ] 證據等級標記（GRADE / Oxford LoE）
- [ ] RSS feed URLs 維護（部分期刊 RSS 已變更）

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
