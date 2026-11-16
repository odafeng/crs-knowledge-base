# 0017. 留言、匿名身分與公開資料邊界

**Status**: Accepted（2026-11-16 由維護者於 [A2 #54](https://github.com/odafeng/crs-knowledge-base/issues/54) 確認；Auth 採 Supabase，見 [ADR-0016](0016-api-data-cloud-boundaries.md)）

## Context

GutHub 規劃讓讀者在文獻頁留言，並支援匿名發言。「登入後對讀者匿名」與「免註冊訪客」需要不同的帳號管理、防濫用及審核安排，不能用同一個匿名 checkbox 代替政策。

現站沒有使用者帳號或讀者留言。既有 `commentary` 指期刊社論、來信、評論等研究內容，不等於讀者討論。現有離線快取與未來 CDN／HTML cache 也必須避免存入使用者身分、私有作者對應或後台資料。

## Decision

### A2 確認的政策

- MVP 要求登入，發文時可選署名或對其他讀者匿名。平台保留必要作者對應，供本人管理留言及維護者處理檢舉。這不是對平台不可識別的匿名。
- 登入方式（2026-11-16 補充確認，對應 A2 完成條件中的「登入方式」）：Google OAuth 與 Email 一次性連結，兩者都經 Supabase Auth；不提供密碼登入。Google OAuth client 與正式環境的寄信服務（SMTP）由 [F1 #75](https://github.com/odafeng/crs-knowledge-base/issues/75) 準備。2026-11-17 維護者決定：staging 先用 Supabase 內建寄信（每小時額度很少，只供測試）；正式 SMTP 需要可設定 DNS 的寄件網域，等 [F4 #79](https://github.com/odafeng/crs-knowledge-base/issues/79) 決定網域時一起設定，在那之前 production 不開放 Email 登入。
- 公開顯示名稱由使用者在首次登入時自行填寫（1–80 字），之後可以修改；不自動帶入 Google 姓名或 email，避免在本人不知情時公開。署名留言保存發文當下的名稱。
- MVP 不開放免註冊留言，也不啟用 Supabase 匿名登入。日後若要開放，需另定 CAPTCHA／Turnstile、頻率限制、清理、升級帳號及跨裝置行為，並修訂本 ADR。
- 審核：每個帳號的第一則留言為 `pending`，經維護者核准才公開；之後的留言直接 `published`，以檢舉與事後隱藏處理。
- 管理角色：MVP 只有維護者一個 admin 角色，可核准／隱藏留言、處理檢舉及查閱匿名留言的作者對應；每次查閱私有身分與每個審核動作都寫入 audit record。
- 保留：留言或帳號刪除時先軟刪除（對外不可見），私有作者對應在刪除後 90 天清除。
- 限制：單則留言最多 2000 字元；每帳號 10 分鐘內最多 5 則、每日最多 50 則。數值由服務端設定，可調整而不需改 schema。

### 實作原則

- 留言使用獨立 `comments` 模型，先提供文獻頁列表、建立與本人管理操作。回覆樹、投票、即時聊天與附件不預建。
- 公開留言只包含必要的公開欄位。匿名留言不返回 account ID、email、OAuth 資料、私有作者對應或可跨頁穩定連結到帳號的識別值。
- 作者對應存放於受保護的資料結構。公開 DTO、DB grant／RLS、view、Data API 與 Realtime 的可見性都要驗證；只在 component 隱藏姓名不算匿名隔離。
- token／session 在伺服器驗證。管理角色不可由使用者可自行編輯的 metadata 或前端參數指定；Supabase secret/service role key 不得進入瀏覽器。
- 作者只能管理自己的留言；批准、隱藏、處理檢舉與查閱私有身分限管理角色並留下 audit record。留言審核不沿用現有醫學內容審核流程。
- 發文長度、頻率、重送去重與 session 建立限制由服務端執行；實際多 instance 部署仍須有效。
- 公開文獻可依策略靜態產生或快取。Auth、私有作者資訊、後台及 mutation 不進共享 HTML/CDN／Service Worker cache；登入相關區域依使用者動態處理。
- 讀者留言不自動進入 provenance、AI 新聞稿或 Paper Watch 發布管線，不能因有人留言就改變文獻的來源／審核狀態。

Auth 採 Supabase。Supabase 匿名登入的使用者也會使用 `authenticated` role；MVP 不啟用匿名登入，權限檢查仍以 claims 判斷（例如 `is_anonymous`），不只檢查已登入，以免日後開啟時被繞過。

## Consequences

- 讀者可以討論實證，而文獻來源、期刊 commentary 與讀者意見仍有清楚邊界。
- 登入後匿名可保留本人操作與檢舉管理能力，但平台必須清楚告知匿名的範圍。
- 私有對應、權限測試與管理稽核增加實作成本；不應只靠畫面測試驗收。
- 要求登入會降低一部分讀者的留言意願；免註冊模式延後，是以參與度換取較低的濫用與管理成本。
- Google OAuth 需要維護 Google Cloud 的 OAuth client 與同意畫面；Email 連結依賴寄信服務的送達率，信件被擋時使用者無法登入。
- 首篇先審意味新使用者第一則留言會延遲出現，且只有維護者一人審核，審核延遲取決於維護者的時間。
- 審核、檢舉及身分查閱需要維護者安排人員與政策；功能上線不等於這些責任已被自動化。

## References

- [A2 #54：匿名與審核政策](https://github.com/odafeng/crs-knowledge-base/issues/54)
- [Job D：身分與留言](https://github.com/odafeng/crs-knowledge-base/milestone/4)
- [C3 #65：公開內容離線與快取](https://github.com/odafeng/crs-knowledge-base/issues/65)
- [Supabase Anonymous Sign-Ins](https://supabase.com/docs/guides/auth/auth-anonymous)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Firebase Anonymous Authentication](https://firebase.google.com/docs/auth/web/anonymous-auth)
