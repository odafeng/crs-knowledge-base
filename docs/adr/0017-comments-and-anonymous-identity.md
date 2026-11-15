# 0017. 留言、匿名身分與公開資料邊界

**Status**: Proposed（待 A2 確認匿名及審核政策，Auth 供應商依 A1）

## Context

GutHub 規劃讓讀者在文獻頁留言，並支援匿名發言。「登入後對讀者匿名」與「免註冊訪客」需要不同的帳號管理、防濫用及審核安排，不能用同一個匿名 checkbox 代替政策。

現站沒有使用者帳號或讀者留言。既有 `commentary` 指期刊社論、來信、評論等研究內容，不等於讀者討論。現有離線快取與未來 CDN／HTML cache 也必須避免存入使用者身分、私有作者對應或後台資料。

## Decision

以下提案由 [A2 #54](https://github.com/odafeng/crs-knowledge-base/issues/54) 確認：

- 建議 MVP 先要求登入，發文時可選署名或對其他讀者匿名。平台保留必要作者對應，供本人管理留言及獲授權人員處理檢舉。這不是對平台不可識別的匿名。
- 若選免註冊留言，使用供應商的匿名 session，另定義 CAPTCHA／Turnstile、頻率限制、清理、升級帳號及跨裝置／清除瀏覽資料後的行為。不能假設匿名登入等於無身分或無權限。
- 留言使用獨立 `comments` 模型，先提供文獻頁列表、建立與本人管理操作。回覆樹、投票、即時聊天與附件不預建。
- 公開留言只包含必要的公開欄位。匿名留言不返回 account ID、email、OAuth 資料、私有作者對應或可跨頁穩定連結到帳號的識別值。
- 作者對應存放於受保護的資料結構。公開 DTO、DB grant／RLS、view、Data API 與 Realtime 的可見性都要驗證；只在 component 隱藏姓名不算匿名隔離。
- token／session 在伺服器驗證。管理角色不可由使用者可自行編輯的 metadata 或前端參數指定；Supabase secret/service role key 不得進入瀏覽器。
- 作者只能管理自己的留言；批准、隱藏、處理檢舉與查閱私有身分依管理角色分權並留下 audit record。保留期間、刪除方式與先審／後審由 A2 指定，不假設現有醫學內容審核就是留言政策。
- 發文長度、頻率、重送去重與 session 建立限制由服務端執行；實際多 instance 部署仍須有效。
- 公開文獻可依策略靜態產生或快取。Auth、私有作者資訊、後台及 mutation 不進共享 HTML/CDN／Service Worker cache；登入相關區域依使用者動態處理。
- 讀者留言不自動進入 provenance、AI 新聞稿或 Paper Watch 發布管線，不能因有人留言就改變文獻的來源／審核狀態。

Auth 供應商依 A1 選定。Supabase 匿名登入的使用者也會使用 `authenticated` role，因此若採 guest 模式，權限要檢查對應 claims，而非只檢查已登入。

## Consequences

- 讀者可以討論實證，而文獻來源、期刊 commentary 與讀者意見仍有清楚邊界。
- 登入後匿名可保留本人操作與檢舉管理能力，但平台必須清楚告知匿名的範圍。
- 私有對應、權限測試與管理稽核增加實作成本；不應只靠畫面測試驗收。
- 免註冊模式進一步增加濫用、session 清理、帳號轉換與使用者失去存取權的處理成本。
- 審核、檢舉及身分查閱需要維護者安排人員與政策；功能上線不等於這些責任已被自動化。

## References

- [A2 #54：匿名與審核政策](https://github.com/odafeng/crs-knowledge-base/issues/54)
- [Job D：身分與留言](https://github.com/odafeng/crs-knowledge-base/milestone/4)
- [C3 #65：公開內容離線與快取](https://github.com/odafeng/crs-knowledge-base/issues/65)
- [Supabase Anonymous Sign-Ins](https://supabase.com/docs/guides/auth/auth-anonymous)
- [Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Firebase Anonymous Authentication](https://firebase.google.com/docs/auth/web/anonymous-auth)
