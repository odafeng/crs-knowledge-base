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

## 檢查

```sh
uv run --frozen ruff check . && uv run --frozen ruff format --check .
uv run --frozen pyright
uv run --frozen pytest
```

測試包含四部分：unit（設定、錯誤格式）、contract（實作的路由必須寫在 `openapi.yaml`，回應要符合其 schema）、smoke（實際啟動 uvicorn 打 `/health`），以及資料庫 integration（`tests/test_db_schema.py`）。

資料庫測試需要先 `supabase start`（見 [supabase/README.md](../../supabase/README.md)），再帶入連線設定。沒有設定時會 skip；CI 設了 `GUTHUB_REQUIRE_DB=1`，缺設定會直接失敗。

```sh
eval "$(supabase status -o env --workdir ../.. | grep -E '^(DB_URL|REST_URL|ANON_KEY|SERVICE_ROLE_KEY)=')"
GUTHUB_TEST_DATABASE_URL=$DB_URL GUTHUB_TEST_REST_URL=$REST_URL \
GUTHUB_TEST_ANON_KEY=$ANON_KEY GUTHUB_TEST_SERVICE_KEY=$SERVICE_ROLE_KEY \
uv run --frozen pytest
```

## 讀取 API（B5）

`/papers`、`/papers/{id}`、`/news`、`/news/{id}`、`/topics`、`/topics/{key}`、`/search` 依 contract 實作：

- 只讀 `app.public_*` view，撤下的內容與指向它的 relation 都不會出現。
- 所有 HTML 欄位（`detailHtml`、治療卡片 `body_html`、robotic 卡片與 timeline）以 nh3 白名單清理。白名單依現有內容實際使用的標籤訂定，`style`、`target` 會被移除。
- 分頁用 opaque cursor（內部是 offset）。內容一週只變動幾次，翻頁期間剛好有資料變動而跳號的機率很低，換取分頁邏輯簡單一致。
- 搜尋的欄位、標題格式與排序（news 在前）沿用網站的搜尋索引。
- 公開回應帶 `Cache-Control: public, max-age=300`；資料庫連不上時回 503 `unavailable`，`/health` 也一樣。

錯誤一律回傳 `{"error": {"code", "message", "requestId"}}`，並附 `X-Request-ID` header。request ID 一律由伺服器產生，client 傳來的值會被忽略。未預期的錯誤回 500，只寫 log，不把內部訊息回給 client。
