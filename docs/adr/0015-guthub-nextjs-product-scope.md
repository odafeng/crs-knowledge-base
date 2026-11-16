# 0015. GutHub 名稱與 Next.js／React 遷移範圍

**Status**: Accepted（產品與前端方向；正式站尚未切換）

## Context

維護者提出將 Seminar Hegemon 改名為 GutHub，改用 Next.js 與 React，並加入署名／匿名留言；對話已確認 React 指前端函式庫。現有程式仍是 ADR-0014 的 Python/Jinja2 網站，已有文獻內容、新聞、Feed、搜尋與離線閱讀。

留言會引入使用者身分、可變資料與管理權限。這些功能需要新的服務分工，不能只換網站名稱就視為架構遷移完成。雲端分工見 ADR-0016、匿名模式見 ADR-0017；ADK 導入時機尚未定案（E4）。

## Decision

- 產品顯示名稱採 GutHub，服務對象仍是醫療專業人員，核心是實證閱讀與討論。前端採 Next.js + TypeScript + React。
- 依既有 v3 視覺方向遷移，保留文獻、詳細證據、主題、機器手臂內容、治療與監管狀態、研究 commentary、新聞、來源／審核標示、Feed、SEO、搜尋、手機操作及公開內容離線閱讀。
- 文獻 ID 與可用的公開路徑優先延續。正式入口直接呈現新版內容，不能用 redirect 包裝舊介面。
- 產品名稱、repository 名稱與正式網域分別處理。2026-11-16 維護者於 [A3 #55](https://github.com/odafeng/crs-knowledge-base/issues/55) 確認：這一階段只把顯示名稱改為 GutHub；repository（`odafeng/crs-knowledge-base`）與現有公開網址都不變，新網域日後另行決定。既有文獻 URL 與 Feed 識別碼沿用現址，不需要轉址。
- 本次 MVP 包含登入、文獻頁留言及 ADR-0017 的匿名模式（登入後可選對其他讀者匿名）。回覆樹、投票、個人收藏、即時聊天與公開 AI 問答不預先納入。
- 現有 v3 在新架構驗收前保留為可建置基線。現站部署缺陷另由 [A4 #56](https://github.com/odafeng/crs-knowledge-base/issues/56) 處理。
- Next.js 專案放在 `apps/web/`，與現行 Python/Jinja2 共存。遷移期間共用 `static/styles/` 與本地字型，API types 由 `contracts/openapi.yaml` 產生並由 CI 檢查同步；前端啟動檢查不連接外部 API、Auth 或資料庫。
- 閱讀頁採 server 端 ISR（2026-11-16 維護者於 C2 #64 開工前確認）：Next.js server component 向 FastAPI 讀資料，頁面每 5 分鐘重新生成，與 API 的 `Cache-Control: public, max-age=300` 一致。內容更新不必重建網站。登入與留言等個人化區域另由使用者端動態處理，不放進共享快取。這需要一個能執行 Next.js server 的環境，由 [F1 #75](https://github.com/odafeng/crs-knowledge-base/issues/75) 提供。
- Jobs 使用 milestones、Steps 使用 issues；實作與驗收狀態不重複寫入本 ADR。供應商與資料分工見 [ADR-0016](0016-api-data-cloud-boundaries.md)，留言政策見 [ADR-0017](0017-comments-and-anonymous-identity.md)。

本 ADR 在 Next.js 正式切換後取代 ADR-0014 的前端實作部分；在此之前，ADR-0014 仍描述目前可執行的網站。

## Consequences

- 閱讀介面與互動功能可以在同一個 React 應用內維護，也能分別測試公開頁面與身分相關流程。
- 現有內容與品質控制有明確的遷移驗收，不會因改框架而被省略。
- Next.js 引入 Node.js runtime、TypeScript、套件升級與新的 CI 工作，維護成本高於現有靜態網站。
- 遷移期間需維持現行與新前端兩條可驗證路徑；正式切換後才整理過渡程式。
- ISR 讓網站在 FastAPI 或資料庫故障時仍可回傳上一次生成的頁面，但新內容最多會晚 5 分鐘出現，而且多了一個需要部署與監控的 Next.js server。
- 大範圍更名容易連帶破壞 canonical、Feed ID、PWA scope 與 CI 設定。只改顯示名稱避開了這個風險，代價是品牌名稱與網址暫時不一致；日後若換網域，canonical、Feed ID 與 PWA scope 的遷移要另開 Step 處理。

## References

- [Job C：Next.js 閱讀介面](https://github.com/odafeng/crs-knowledge-base/milestone/3)
- [A5 #57：README 與 ADR](https://github.com/odafeng/crs-knowledge-base/issues/57)
- [Next.js 部署方式](https://nextjs.org/docs/app/getting-started/deploying)
