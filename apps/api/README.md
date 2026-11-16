# GutHub API

FastAPI 服務，依 [ADR-0016](../../docs/adr/0016-api-data-cloud-boundaries.md) 部署在 Cloud Run。API 格式以 [`contracts/openapi.yaml`](../../contracts/openapi.yaml) 為準，FastAPI 自動產生的 `/docs` 與 `/openapi.json` 已關閉。

## 本機開發

需要 [uv](https://docs.astral.sh/uv/)。Python 版本由 `.python-version` 固定為 3.12，依賴由 `uv.lock` 鎖定。

```sh
cd apps/api
uv sync --frozen
uv run --frozen uvicorn guthub_api.main:app --reload
curl localhost:8000/api/v1/health
```

## 設定

設定只從 `GUTHUB_*` 環境變數讀取（`guthub_api/settings.py`）。祕密不寫進 repository，也不會送到前端。

| 變數 | 值 | 預設 |
|---|---|---|
| `GUTHUB_ENVIRONMENT` | `development`、`test`、`staging`、`production` | `development` |
| `GUTHUB_DATABASE_URL` | PostgreSQL 連線字串，使用被授予 `guthub_api` 的 login role（見 [supabase/README.md](../../supabase/README.md)） | 無；`staging`、`production` 缺少時啟動失敗 |
| `GUTHUB_SUPABASE_URL` | Supabase project URL，例如 `http://127.0.0.1:54321`。用它的 Auth JWKS 驗證登入 token | 無；未設定時需要登入的端點回 503 |
| `GUTHUB_CORS_ORIGINS` | 允許從瀏覽器呼叫 API 的網站 origin，JSON 陣列，例如 `["https://guthub.example"]` | `[]`（不開 CORS） |

## 檢查

```sh
uv run --frozen ruff check . && uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen pytest
```

測試包含四部分：unit（設定、錯誤格式）、contract（實作的路由必須寫在 `openapi.yaml`，回應要符合其 schema）、smoke（實際啟動 uvicorn 打 `/health`），以及資料庫 integration（`tests/test_db_schema.py`）。

資料庫測試需要先 `supabase start`（見 [supabase/README.md](../../supabase/README.md)），再帶入連線設定。沒有設定時會 skip；CI 設了 `GUTHUB_REQUIRE_DB=1`，缺設定會直接失敗。

```sh
eval "$(supabase status -o env --workdir ../.. | grep -E '^(API_URL|DB_URL|REST_URL|ANON_KEY|SERVICE_ROLE_KEY)=')"
GUTHUB_TEST_DATABASE_URL=$DB_URL GUTHUB_TEST_REST_URL=$REST_URL GUTHUB_TEST_SUPABASE_URL=$API_URL \
GUTHUB_TEST_ANON_KEY=$ANON_KEY GUTHUB_TEST_SERVICE_KEY=$SERVICE_ROLE_KEY \
uv run --frozen pytest
```

## 帳號與登入（D1）

登入由 Supabase Auth 處理（Google 與 Email 一次性連結，ADR-0017）。API 只接受 `Authorization: Bearer <access token>`，不讀 cookie；token 用 Supabase 的 JWKS 驗章（只接受 ES256／RS256），並檢查 `aud`、`iss`、`exp`、`role`，匿名登入的 session 一律拒絕。設計與取捨見 [ADR-0020](../../docs/adr/0020-browser-session-and-bearer-api.md)。

- `GET /me`：本人的顯示名稱與是否為管理者。還沒設定名稱時 `displayName` 是 `null`。
- `PUT /me`：設定或修改顯示名稱（去頭尾空白後 1–80 字，不可含控制字元）；第一次設定時建立帳號。
- 管理者只看 `app.accounts.is_admin`，由維護者直接在資料庫設定；token 的 metadata 不能授權。`accounts.require_admin` 給 D5 的審核端點使用。

回應都帶 `Cache-Control: private, no-store` 與 `Vary: Authorization`。

## 讀者留言（D2）

留言是純文字，存在獨立的 `app.comments`，和期刊 commentary 分開，也不會成為文獻的證據或來源（ADR-0017）。

| 端點 | 誰可以用 | 說明 |
|---|---|---|
| `GET /papers/{id}/comments` | 所有人 | 只列已公開、未刪除的留言；文獻撤下後回 404。依 `(created_at, id)` 分頁，翻頁期間有新留言也不會重複或漏掉 |
| `POST /papers/{id}/comments` | 已設定顯示名稱的讀者 | 署名留言保存發文當時的名稱；匿名留言不回傳任何作者資訊。帳號第一則留言是 `pending`，由資料庫 trigger 決定 |
| `GET /me/comments` | 本人 | 自己的留言與審核狀態（含 `pending`、`hidden`） |
| `PATCH`、`DELETE /comments/{id}` | 只有作者（管理者也不行） | 修改不改變審核狀態；刪除是軟刪除，90 天後清除作者對應 |
| `POST /comments/{id}/reports` | 已設定顯示名稱的讀者 | 只能檢舉看得到的留言，不能檢舉自己的；同一則只能檢舉一次（409） |

本文 1–2000 字元、檢舉理由 1–1000 字元，只允許換行與 tab 兩種控制字元。發文頻率限制在 D4、審核與隱藏在 D5。

## 讀取 API（B5）

`/papers`、`/papers/{id}`、`/news`、`/news/{id}`、`/topics`、`/topics/{key}`、`/search` 依 contract 實作：

- 只讀 `app.public_*` view，撤下的內容與指向它的 relation 都不會出現。
- 所有 HTML 欄位（`detailHtml`、治療卡片 `body_html`、robotic 卡片與 timeline）以 nh3 白名單清理。白名單依現有內容實際使用的標籤訂定，`style`、`target` 會被移除。
- 分頁用 opaque cursor（內部是 offset）。內容一週只變動幾次，翻頁期間剛好有資料變動而跳號的機率很低，換取分頁邏輯簡單一致。
- 搜尋的欄位、標題格式與排序（news 在前）沿用網站的搜尋索引。
- 公開回應帶 `Cache-Control: public, max-age=300`；資料庫連不上時回 503 `unavailable`，`/health` 也一樣。

錯誤一律回傳 `{"error": {"code", "message", "requestId"}}`，並附 `X-Request-ID` header。request ID 一律由伺服器產生，client 傳來的值會被忽略。未預期的錯誤回 500，只寫 log，不把內部訊息回給 client。
