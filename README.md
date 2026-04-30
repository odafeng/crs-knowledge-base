# CRS Knowledge Base

> 大腸直腸外科臨床決策知識庫 — 行動端 Progressive Web App

[![PWA](https://img.shields.io/badge/PWA-ready-1a365d)](https://web.dev/progressive-web-apps/)
[![Deploy](https://img.shields.io/badge/GitHub%20Pages-live-3182ce)](https://odafeng.github.io/crs-knowledge-base/)
[![License: MIT](https://img.shields.io/badge/License-MIT-38a169)](#授權)
[![Lang](https://img.shields.io/badge/Lang-zh--TW-1a202c)](#)

🔗 **Live**：<https://odafeng.github.io/crs-knowledge-base/>

---

## 簡介

**CRS Knowledge Base**（Colorectal Surgery Knowledge Base）是一套面向 **大腸直腸外科臨床醫師** 的口袋型知識庫，主打 **離線可用**、**單頁載入**、**手術房／病房床邊查詢友善**。

設計目標是讓主治醫師、總醫師、住院醫師可以在 30 秒內查到：

- 某個生物標記（biomarker）對應的當代治療路徑
- 關鍵試驗（landmark trial）的核心數據與時間軸
- 機器人手術技術重點與證據基礎

不是一個 Wikipedia，而是一份 **隨身臨床備忘錄**。

> ⚠️ **臨床免責聲明**：本網站僅供醫學教育與臨床參考用途，**不構成醫療建議**。所有臨床決策仍應由具執照之醫師依個別病人狀況綜合判斷。

---

## 功能特色

- 📱 **行動優先設計** — 採用單欄 + sticky header，適合手術衣口袋掏出來就查
- 🔌 **完全離線可用** — Service Worker（network-first）快取整個知識庫，醫院 Wi-Fi 死角也能用
- 🏠 **可加入主畫面** — PWA manifest 支援 iOS / Android「加到主畫面」，行為近似原生 App
- 🧬 **生物標記導向** — mCRC 章節以 biomarker 為主軸（BRAF / KRAS / MSI / HER2 / RAS-wt）
- 📊 **試驗時間軸視覺化** — Beacon → Breakwater 等 landmark trials 以 timeline + 階梯圖呈現療效演進
- 📄 **每篇證據獨立頁面** — 每個 trial 一個 HTML，方便引用、轉貼、列印

---

## 主題涵蓋

| 領域 | 子主題 | 狀態 |
|---|---|---|
| **mCRC** | BRAF V600E Mutant | ✅ 上線（含 BEACON、BREAKWATER 系列證據） |
| | KRAS G12C | 🟡 框架完成，證據陸續補齊 |
| | MSI-H / dMMR | 🟡 框架完成 |
| | HER2 Amplification | 🟡 框架完成 |
| | RAS-wt / BRAF-wt（Anti-EGFR） | 🟡 框架完成 |
| **機器人手術** | TME（全直腸繫膜切除） | ✅ 上線 |
| | Anastomosis（吻合技術） | ✅ 上線 |
| | CME（完全結腸繫膜切除） | ⏳ 規劃中 |
| | Others | ⏳ 規劃中 |
| **肛門手術** | — | ⏳ 規劃中 |
| **其他** | — | ⏳ 規劃中 |

---

## 技術架構

刻意維持 **零建置流程（zero build）** —— 不用 npm、不用 webpack、不用框架，直接 HTML/CSS/JS。

| 項目 | 選用 |
|---|---|
| 前端 | 原生 HTML5 + CSS3 + Vanilla JS（單檔 SPA） |
| 樣式 | 自寫 CSS variables（無 Tailwind / 無 CSS 框架） |
| 離線 | Service Worker v11，network-first 策略 |
| 安裝 | Web App Manifest（standalone display） |
| 部署 | GitHub Pages（main branch 根目錄） |
| 字型 | system font stack（含 Noto Sans TC fallback） |

選擇 vanilla 的理由：知識庫內容更新頻率 >> 介面改版頻率，沒必要為了 React/Vue 多吃一層複雜度與包大小。

---

## 專案結構

```
crs-knowledge-base/
├── index.html              # 單檔 SPA：所有路由、樣式、互動邏輯
├── manifest.json           # PWA manifest
├── sw.js                   # Service Worker（network-first 快取）
├── icons/
│   ├── icon-192.png
│   └── icon-512.png
└── docs/                   # 證據文獻頁面（每篇 trial 一個 HTML）
    └── mCRC-BRAF-V600E/
        ├── Kopetz_NEJM_2019_BEACON.html
        ├── Tabernero_JCO_2021_BEACON.html
        ├── Kopetz_NatMed_2025_BREAKWATER.html
        ├── Elez_NEJM_2025_BREAKWATER.html
        ├── Kopetz_ESMO_2025_BREAKWATER_ctDNA.html
        ├── Kopetz_ESMO_2025_BREAKWATER_SubsequentTx.html
        └── Kopetz_ASCOGI_2026_BREAKWATER_Cohort3.html
```

---

## 本地開發

由於是純靜態網站，最低需求只要一個瀏覽器。但若要測試 Service Worker，**必須跑在 HTTP server 而非 `file://`**。

```bash
# 推薦：Python 內建 server
git clone https://github.com/odafeng/crs-knowledge-base.git
cd crs-knowledge-base
python3 -m http.server 8000
# 開啟 http://localhost:8000
```

或使用任何熟悉的工具：`npx serve`、`php -S localhost:8000`、VSCode Live Server 皆可。

### Service Worker 除錯小技巧

PWA 在開發時最容易踩雷的地方是 SW 把舊版本 cache 住。除錯時：

1. Chrome DevTools → Application → Service Workers
2. 勾 **Update on reload** 與 **Bypass for network**
3. 改完 `sw.js` 後記得把 `CACHE_NAME` 版本號往上加（`crs-kb-v11` → `crs-kb-v12`）

---

## 新增證據文獻

### 命名規則

```
docs/<TopicSlug>/<FirstAuthor>_<Journal>_<Year>_<TrialName>[_<Subtopic>].html
```

例：
- `Kopetz_NEJM_2019_BEACON.html`
- `Kopetz_ESMO_2025_BREAKWATER_ctDNA.html`

### 新增步驟

1. 在 `docs/<TopicSlug>/` 下建立新的 `.html` 檔（可直接複製既有檔案改寫）
2. 每篇至少包含：`<title>`、`<h1>`、Abstract、Key Results、Conclusions
3. 在 `index.html` 對應的子主題 view 加入連結
4. 將 `sw.js` 的 `CACHE_NAME` 版本號 +1，確保 PWA 使用者能取得新內容
5. push 到 `main` → GitHub Pages 自動部署

---

## Roadmap

- [ ] 補齊 mCRC 其他 biomarker 章節的 evidence pages
- [ ] 機器人手術加上 CME、TaTME、單孔手術子主題
- [ ] 肛門手術章節（痔瘡、廔管、肛裂）
- [ ] 加入「快速搜尋」功能（client-side fuzzy search）
- [ ] 中英雙語切換（i18n）
- [ ] 證據等級標記（GRADE / Oxford LoE）

---

## 作者

**黃士峯（Shih-Feng Huang, MD）**
Colorectal Surgeon, Kaohsiung Veterans General Hospital

- 🌐 <https://shihfenghuang.com>
- 🐙 [@odafeng](https://github.com/odafeng)
- 🆔 ORCID: [0000-0002-8037-4074](https://orcid.org/0000-0002-8037-4074)

---

## 授權

本專案以 [MIT License](LICENSE) 釋出。

各篇 evidence pages 內容為原始文獻之摘要與整理，**所引用之臨床試驗數據與圖表智慧財產權屬於原作者與原出版單位**；本網站使用屬合理使用（fair use）範圍之教育用途。
