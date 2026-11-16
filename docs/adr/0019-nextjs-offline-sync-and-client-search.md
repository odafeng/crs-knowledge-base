# 0019. Next.js 版的離線快取改為執行期對照公開索引同步

**Status**: Accepted（Next.js 網站取代 ADR-0014 的建置期快取清單；隱私邊界依 ADR-0017）

## Context

現站的 Service Worker 由 `sitegen` 在建置時產生：快取清單列出全站頁面，版本號跟著內容雜湊變，撤下的頁面不會出現在下一版。Next.js 網站改成 ISR（ADR-0015），內容更新不必重新建置，所以沒有「每次發布產生新快取清單」這個時間點。

C3 #65 要保留離線閱讀與搜尋，同時符合 ADR-0017：Auth、留言 mutation、私有作者對應與管理 API 不能進 Service Worker cache，登出或換帳號後不能讀到前一人的資料。

另外，首頁、`/updates/` 等索引頁在 request 時才向 API 讀資料（`connection()`，build 時不呼叫 API），Next.js 會替這類動態頁預設加上 `Cache-Control: private, no-store`。這些頁面其實沒有任何個人資料。

## Decision

- `/sw.js` 放在 `apps/web/public/`，由每個頁面註冊。頁面註冊後會請 Service Worker 同步，十分鐘內最多同步一次。
- 同步以 `/search.json` 為依據：先存下索引，再刪掉快取中已經不在索引裡的 `/papers/*`、`/news/*`，接著補存新出現的頁面，以及這些頁面引用的 `/_next/static/` 檔案。最後刪掉沒有任何已存頁面或樣式表引用的 build 檔，避免每次部署後舊檔一直累積。
- 頁面一律 network-first：連得上網路就拿最新版並更新快取；伺服器回 404 或 410 時立即刪掉該頁的快取。`/_next/static/` 的檔名帶雜湊，採 cache-first。
- Service Worker 只處理同源的 GET。`/api`、`/auth`、`/me`、`/account`、`/admin` 開頭的路徑、帶 `Authorization` 的請求，以及 RSC payload 一律交還瀏覽器處理。回應帶 `private` 或 `no-store` 的也不存。
- 沒有個人資料的動態索引頁，在 `next.config.ts` 逐一列出並明確標為 `public, max-age=0, must-revalidate`。這份清單只能逐條加；帳號與管理頁面不列入，維持 Next.js 預設的 private。
- 搜尋留在瀏覽器端，比對 `/search.json`，索引內容和現站相同，離線時也能搜尋。B5 的 `GET /search` API 保留給之後的其他使用端。
- 啟用時清掉舊版本（`guthub-*`）與現站（`seminar-hegemon-*`）的快取。網域切換到 Next.js 後，現站留在讀者裝置上的快取會在這一步清掉。

## Consequences

- 撤下的文獻在下一次同步，或讀者線上再次開啟該頁時就會從離線副本消失，不必等重新建置。不過讀者若一直離線，裝置上的舊副本會保留到下次連線。
- 同步只補新頁，不會重抓已存的頁面。內容修訂要等讀者線上開過該頁，離線副本才會更新。
- 第一次同步會向網站要約 50 個頁面。ISR 讓這些請求多半直接由快取回應，但流量仍比只存讀者看過的頁面多。
- 公開與私有的界線現在由兩份清單決定：`next.config.ts` 的公開動態頁，以及 `sw.js` 的私有路徑。新增帳號相關路徑時，若不在上述私有路徑前綴之下，必須同時更新 `sw.js`。
- 搜尋結果順序依 API（新的在前），現站則依資料檔順序。兩邊找到的條目相同，但只顯示前 8 筆時，看到的條目可能不同。
- 字型只會在讀者線上載入頁面後才存進快取。若讀者第一次載入就離線，頁面會改用系統字型，版面與內容不受影響。
- Service Worker 的邏輯由 `src/lib/service-worker.test.ts` 在 VM 中執行真正的 `sw.js` 測試，瀏覽器流程由 `tools/next-offline.js` 在 CI 驗證。撤下流程只有單元測試，E2E 沒有真的從資料庫撤下內容。
