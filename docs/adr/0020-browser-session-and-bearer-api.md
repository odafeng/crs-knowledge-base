# 0020. 登入 session 只存在瀏覽器，API 只接受 Bearer token

**Status**: Accepted（D1 #67；依 ADR-0016 的服務分工與 ADR-0017 的登入政策）

## Context

ADR-0017 決定以 Supabase Auth 提供 Google 與 Email 一次性連結登入，並要求：session 不進共享 HTML、CDN 或 Service Worker cache；管理角色不能來自使用者可編輯的 metadata；Supabase 的 secret key 不能進瀏覽器；用 cookie 驗證身分的 mutation 要有 CSRF 防護。

Next.js 的公開頁面以 ISR 產生，並由 CDN 與 Service Worker 快取（ADR-0019）。寫入一律經 FastAPI，FastAPI 部署在 Cloud Run，和網站不同 origin（ADR-0016）。

Supabase 官方的 Next.js 做法（`@supabase/ssr`）把 session 放在 cookie，並在 middleware 裡每個 request 都更新一次。這樣一來，公開頁面的回應會帶 `Set-Cookie`，HTML 也可能依讀者不同，和「公開頁面可以共用快取」互相衝突。另外，PKCE 的 Email 連結只能在送出登入要求的那個瀏覽器使用，而讀者常常在電腦上要求登入、在手機上開信。

## Decision

- **Session 只放在瀏覽器**。用 supabase-js（PKCE flow）把 session 存在 localStorage。伺服器端渲染的頁面完全不讀 session，也不設 middleware；頁首的登入狀態是 client component，伺服器端一律輸出未登入的版本。所以每個人拿到的 HTML 都一樣，快取裡不會有任何人的身分。
- **瀏覽器直接呼叫 FastAPI，token 放在 `Authorization: Bearer`**。FastAPI 不讀 cookie，CORS 只允許 `GUTHUB_CORS_ORIGINS` 列出的網站 origin，而且不開 credentials。沒有任何靠 cookie 驗證的 mutation，CSRF 也就沒有可利用的地方，不需要另外做 CSRF token。
- **FastAPI 在伺服器驗 token**：用 Supabase Auth 的 JWKS 驗章，只接受 ES256／RS256（拒絕共用 secret 與 `alg: none`）；檢查 `aud = authenticated`、`iss`、`exp`、`iat`、`sub` 是 UUID、`role = authenticated`，並拒絕 `is_anonymous` 的 session。JWKS 快取 10 分鐘，遇到不認得的 key ID 會重抓，所以輪換金鑰不必重啟；JWKS 抓不到時回 503，不會放行。
- **管理角色只看資料庫**：每個 request 都讀 `app.accounts.is_admin`，由維護者直接在資料庫設定。token 裡的 user／app metadata 不參與授權。
- **顯示名稱**：新增 `GET /me`、`PUT /me`。第一次設定名稱時才建立 `app.accounts`；名稱不會從 Google 或 Email 自動帶入。
- **Email 連結改用 token hash**：自訂的信件範本把連結指向網站的 `/auth/callback/?token_hash=…&type=email`，由頁面呼叫 `verifyOtp` 換成 session，因此在任何瀏覽器或裝置開啟都能登入。Google 登入走 PKCE code，回到同一個頁面。頁面一讀到 token 就把它從網址列移除；`/auth/*` 與 `/account/` 回應 `Cache-Control: private, no-store`。
- **登出**用 `signOut({ scope: "local" })`，只登出這台裝置。前端帳號狀態每次登入或登出都換一個世代編號；前一位讀者較晚回來的 `/me` 結果會直接丟掉，不會顯示給下一位。
- build 時有設定 `NEXT_PUBLIC_SUPABASE_URL`、`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 與 `NEXT_PUBLIC_GUTHUB_API_URL`，網站才會顯示登入入口；`NEXT_PUBLIC_AUTH_GOOGLE=1` 才顯示 Google 按鈕。

## Consequences

- 公開頁面可以照常交給 CDN 與 Service Worker 快取。HTML 本來就不含身分，快取設定出錯也不會把一個人的資料給另一個人看。
- token 放在 localStorage，網站上任何 script 都讀得到；一旦出現 XSS，session 就會外洩。`@supabase/ssr` 的 cookie 同樣能被 JavaScript 讀取，所以並沒有比較差，但也不如由伺服器代管、設成 httpOnly cookie 的做法安全。目前靠的是：不載入第三方 script、內容 HTML 由 API 以 allowlist 清理；CSP 尚未設定。
- 登出後，已發出的 access token 仍可用到過期（`jwt_expiry` 3600 秒）。FastAPI 只驗簽章，不查 session 是否已撤銷，被偷走的 token 最多可用一小時。要即時撤銷，得在 Supabase 管理的 `auth` schema 上給 `guthub_api` 讀取權限，這次沒有做。
- 伺服器端無法渲染因人而異的內容。D3 的留言表單、本人留言狀態等都必須是 client component，透過 API 取得。
- `NEXT_PUBLIC_*` 在 build 時寫進程式，staging 與 production 必須各自 build。
- 跨 origin 的 PUT／POST 需要 CORS preflight，多一次往返（瀏覽器快取 10 分鐘）。
- 正式環境的 Auth 設定（Site URL、Redirect URLs、信件範本、SMTP、Google provider）要在 Supabase 後台手動設定，清單在 `supabase/README.md`。這些設定和 `config.toml` 是兩份，可能不同步；F2 的 staging 驗收要逐項確認。
- E2E 以 Mailpit 實際寄出並開啟 Email 連結，也測換帳號與登出；Google 登入要等 F1 提供 OAuth client，目前沒有自動測試。

## References

- [D1 #67](https://github.com/odafeng/crs-knowledge-base/issues/67)
- [ADR-0016](0016-api-data-cloud-boundaries.md)、[ADR-0017](0017-comments-and-anonymous-identity.md)、[ADR-0019](0019-nextjs-offline-sync-and-client-search.md)
- [Supabase: Server-Side Auth for Next.js](https://supabase.com/docs/guides/auth/server-side/nextjs)
- [Supabase: JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys)
- [Supabase: Email templates](https://supabase.com/docs/guides/auth/auth-email-templates)
