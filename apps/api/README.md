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

錯誤一律回傳 `{"error": {"code", "message", "requestId"}}`，並附 `X-Request-ID` header。request ID 一律由伺服器產生，client 傳來的值會被忽略。未預期的錯誤回 500，只寫 log，不把內部訊息回給 client。
