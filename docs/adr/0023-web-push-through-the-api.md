# 0023. Web Push 訂閱改走 API，新消息由排程 job 各推一次

**Status**: Accepted（2026-11-17；C5 #95）

## Context

現站（ADR-0014）帶來了推播程式：瀏覽器用 Supabase 的公開金鑰呼叫 Data API 上的 `push_subscribe` RPC 存訂閱，再由 `python -m push.send` 手動對某一則消息發送。實際上這套從來沒有啟用過：repository 沒有設定 `PUSH_PUBLIC_KEY`，現站頁面沒有推播按鈕，也沒有任何 workflow 呼叫發送程式。所以沒有既有的訂閱者要搬。

新架構有三條規則和舊做法衝突：
- ADR-0020：瀏覽器不直接碰 Supabase Data API，寫入都經過 FastAPI。
- F3 #78：維護期間要能用一個開關暫停所有寫入。
- 現站的手動發送，在 Next.js 的 ISR 與內容資料庫之下，沒有東西保證一則消息只推一次。

## Decision

- 訂閱存在新 project 的 `app.push_subscriptions`。瀏覽器呼叫 `PUT`／`DELETE /api/v1/push/subscription`，只送 endpoint 和兩把金鑰。這兩個是 contract 中唯二不需要登入的寫入，因為訂閱只代表一個瀏覽器，不連到帳號。endpoint 只接受各家瀏覽器的推播服務網址，API 和資料表各檢查一次。
- 發送由 `python -m guthub_api.maintenance announce-news` 負責，以 Cloud Run job 定時執行。每則消息在 `app.push_announcements` **先佔位再發送**，所以重跑 job、頁面重新產生或重新部署都不會重送；代價是發送中途當機時，那一則不會補送。只推最近 2 天發布的消息；migration 把既有消息標成已推過，第一次啟用時不會一次推出一整批舊消息。
- 推播服務回 404／410 的訂閱直接刪除。讀者關閉推播時，瀏覽器端先取消訂閱，再呼叫 API 刪除；API 刪除失敗時，下次發送會收到 410，到時再刪。
- 網站在 build 時有 `NEXT_PUBLIC_PUSH_PUBLIC_KEY` 才顯示推播按鈕；發送 job 只在 repository 變數 `PUSH_ENABLED=true` 時部署。VAPID 私鑰放 Secret Manager（`vapid-private-key`），不進前端。

## Consequences

- 推播和留言共用同一個 API、同一個暫停開關與同一組 DB 權限，維運只需要看一處。
- 匿名寫入的 endpoint 可能被灌假的訂閱。目前只靠網址白名單與金鑰格式擋，沒有頻率限制；假訂閱會在發送時被推播服務回 404／410 後刪除，但在那之前會佔資料表空間、拖慢發送。若真的被濫用，要再加限制。
- 先佔位再發送的做法保證不重送，但不保證送達：job 在佔位後、送完前中斷，那則消息就不會再推。
- 定時執行代表通知會比發布晚，最多晚一個排程間隔。
- 原本 `push/` 下的發送工具與 SQL 範本保留給現站，正式切換（F4）後就不再使用。

## References

- [C5 #95](https://github.com/odafeng/crs-knowledge-base/issues/95)
- [ADR-0014](0014-generated-multipage-site.md)、[ADR-0020](0020-browser-session-and-bearer-api.md)、[docs/runbook-cutover.md](../runbook-cutover.md)
