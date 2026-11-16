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
supabase start -x realtime,storage-api,imgproxy,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
supabase db reset          # 在乾淨資料庫上重新套用全部 migration
```

本機寄出的登入信在 Mailpit（`supabase status` 的 `MAILPIT_URL`）查看。

資料庫測試在 `apps/api/tests/test_db_schema.py`，指令見 [apps/api/README.md](../apps/api/README.md)。

## Migration 規則

- migration 只往前加，不修改已套用過的檔案。要撤銷 schema 變更，就寫一個新的 migration 反向處理，而且要在 `supabase db reset` 與測試都通過後才合併。
- 會刪資料的變更（drop column／table、縮小型別）要先在 staging 備份並演練還原，再上 production。
- production 出問題時的還原方式：
  - schema 錯誤但資料沒壞：寫 forward-fix migration。
  - 資料被破壞：用 Supabase 的備份或 PITR 還原到變更前的時間點，再重放之後的寫入。
  - 實際演練由 [F3 #78](https://github.com/odafeng/crs-knowledge-base/issues/78) 負責，這份 README 不代表已演練過。

## 內容匯入（B4 #61）

`import_content.py`（repo 根目錄）把 `data/*.json` 和 `docs/` 的詳細 HTML 單向複製到 `app` schema。切換前 JSON 仍是權威來源，資料庫只是可以重建的副本，匯入也不會寫回 JSON。

```sh
python import_content.py --dry-run                                  # 只檢查與產生 manifest，不連資料庫
python import_content.py --database-url "$URL" --dry-run            # 在 transaction 裡實際跑一遍，回報變動後 rollback
python import_content.py --database-url "$URL" --manifest out.json  # 正式匯入
```

`$URL` 也可以改用 `GUTHUB_IMPORT_DATABASE_URL` 環境變數傳入，連線的 role 必須擁有 `app` 的表（`guthub_api` 不能寫內容）。

- 整批在一個 transaction 內，任何錯誤都會整批 rollback，資料庫不會停在一半的狀態。資料檢查錯誤（缺少文件、未知主題、news 沒有審核狀態）會在連資料庫之前就停止。
- 重跑時只更新有變動的列。relations 和期刊 commentary 依 paper 整批替換；來源中已經消失的 paper 和 news 會標記 `withdrawn_at`，不刪除，因為讀者留言可能參照它們。來源恢復後會自動解除撤下。
- manifest 記錄來源檔（JSON 與被引用的 `docs/` 文件）的 sha256，以及每張表的筆數和內容 hash。兩次匯入的 manifest 相同，就代表結果相同。
- 還原：資料庫內容可以隨時從 git 裡的 JSON 重建，用目標 commit 的檔案重跑匯入即可。如果要回到匯入前的資料庫狀態，用 Supabase 的備份或 PITR。

`topics.metrics`（Paper Watch agent 的輸入）、`topics.soc_title`、`papers.source_file` 雖然不在公開 contract 裡，也一併保存，切換時才不會遺失。

## 各環境要另外做的事（F1 #75）

`guthub_api` 是 `nologin` role。每個環境要建立自己的 login role 並授予 `guthub_api`，密碼由祕密管理注入，不寫進 migration：

```sql
create role guthub_api_login login password '<from secret manager>' in role guthub_api;
```

### 登入設定（D1 #67）

`config.toml` 的 Auth 設定只作用在本機。staging 與 production 要在各自的 project 設定同樣的內容：

- **Site URL** 設為該環境網站的 origin；**Redirect URLs** 加入 `<origin>/auth/callback/`。
- **Email 範本**：Magic Link 與 Confirm signup 都改用 `supabase/templates/sign-in.html` 的內容。連結指向網站的 `/auth/callback/?token_hash=…&type=email`，在任何瀏覽器或裝置開啟都能登入；預設範本的 PKCE 連結只能在送出要求的同一個瀏覽器使用。
- **SMTP**：正式寄信服務（ADR-0017）。內建寄信每小時只有少量額度，只適合測試。
- **Google**：建立 OAuth client 後在 Auth providers 啟用，callback 為 `https://<project>.supabase.co/auth/v1/callback`；網站 build 時設 `NEXT_PUBLIC_AUTH_GOOGLE=1`。
- 匿名登入維持關閉。
