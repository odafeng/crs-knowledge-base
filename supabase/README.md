# Supabase 資料庫

Schema 與權限設計見 [ADR-0016](../docs/adr/0016-api-data-cloud-boundaries.md)（資料庫存取與權限執行層）和 [ADR-0017](../docs/adr/0017-comments-and-anonymous-identity.md)。

## 結構

所有表都在 `app` schema，這個 schema 不在 `config.toml` 的 `[api] schemas` 裡，所以 Data API 碰不到。`anon`、`authenticated`、`service_role` 沒有任何 grant；RLS 全開，只有 `guthub_api` 有 policy。FastAPI 以 `guthub_api` 存取，身分規則（只能改自己的留言、審核、查閱匿名作者）寫在 FastAPI，資料庫只負責約束：

- 帳號第一則留言一律 `pending`，之後的留言直接 `published`（trigger，呼叫端傳入的 status 會被忽略）
- `moderation_events` 只能新增；`guthub_api` 不能刪除留言或帳號，也不能修改內容表
- `app.purge_deleted_authors()` 清除刪除超過 90 天的作者對應與帳號
- `public_papers`、`public_news`、`public_comments` 只包含公開內容，沒有作者對應

## 本機

需要 Docker 與 [Supabase CLI](https://supabase.com/docs/guides/cli)。

```sh
supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset          # 在乾淨資料庫上重新套用全部 migration
```

資料庫測試在 `apps/api/tests/test_db_schema.py`，指令見 [apps/api/README.md](../apps/api/README.md)。

## Migration 規則

- migration 只往前加，不修改已套用過的檔案。要撤銷 schema 變更，就寫一個新的 migration 反向處理，而且要在 `supabase db reset` 與測試都通過後才合併。
- 會刪資料的變更（drop column／table、縮小型別）要先在 staging 備份並演練還原，再上 production。
- production 出問題時的還原方式：
  - schema 錯誤但資料沒壞：寫 forward-fix migration。
  - 資料被破壞：用 Supabase 的備份或 PITR 還原到變更前的時間點，再重放之後的寫入。
  - 實際演練由 [F3 #78](https://github.com/odafeng/crs-knowledge-base/issues/78) 負責，這份 README 不代表已演練過。

## 各環境要另外做的事（F1 #75）

`guthub_api` 是 `nologin` role。每個環境要建立自己的 login role 並授予 `guthub_api`，密碼由祕密管理注入，不寫進 migration：

```sql
create role guthub_api_login login password '<from secret manager>' in role guthub_api;
```
