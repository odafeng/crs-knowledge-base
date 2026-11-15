# 0014. 以 v3 網站產生器取代單檔 SPA

**Status**: Accepted（取代 ADR-0001 的前端與部署方式；資料仍依 ADR-0006）

## Context

使用者指定以 `seminar-hegemon-site-v3.zip` 更新整個網站，並明確要求直接替換原站，不使用 redirect。zip 提供 Python/Jinja2 多頁版型、新聞稿、Feed 與推播程式，但尚未接上 repo 的 CI，也沒有離線快取。

## Decision

- 以 `build.py`、`sitegen/`、`templates/`、`static/` 作為新版來源。GitHub Actions 建置到 `site/`，測試通過後將該產物部署到原本的 GitHub Pages 網址。
- Pages 的 publishing source 設為 `workflow`，部署工作先檢查此設定，避免 repo 根目錄的 README 被另一條 branch build 發布成首頁。產物包含 `build-info.json`，記錄建置時的 `GITHUB_SHA`；本機未設定時為 `null`。
- 移除根目錄的舊 SPA、manifest、Service Worker 及舊圖示。新版首頁直接輸出內容，不產生 redirect 頁或 hash 轉址。
- `data/papers.json` 保留為文獻資料來源，`docs/**/*.html` 保留為詳細證據的內容來源，內文套入新版文獻頁或機器手臂主題頁，不另外部署舊 HTML。
- 納入 zip 的 7 篇新聞稿至 `data/news.json`，保留 AI 未審標示與 `noindex`。建置時強制檢查新聞稿數字是否出現在對應文獻條目；這項檢查不等於語意或醫學事實審核。
- Paper Watch、人工接受與撤下流程繼續更新文獻資料及詳細內容。Service Worker 的快取清單與版本改由網站建置產生，無須由發布程式修改。
- 推播沿用 zip 的程式與設定介面；未設定公開金鑰與訂閱 API 時隱藏按鈕。此次未建立訂閱後端，也未發送通知。

## Consequences

- 各頁可直接開啟，具備獨立網址、metadata、搜尋與 Feed；詳細證據內容保留在新版介面。
- 建置產生完整離線快取，內容異動會改變快取版本，撤下的頁面不會留在下一版產物。
- CI 新增 Jinja2、推播測試依賴與 Node/Playwright 檢查，建置時間比原本長。
- 舊 hash 與 `docs/` 網址沒有相容轉址；既有書籤需改用新版網址。
- 新聞稿目前需手動維護，Paper Watch 尚未串接 AI 寫稿；Web Push 尚未在實機測試。
