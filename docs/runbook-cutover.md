# 正式切換、rollback 與告警 runbook

對應 F3 #78。寫給另一位維護者：照順序執行就能完成切換或退回，不需要先讀完所有 ADR。背景與取捨見 ADR-0016（環境）、ADR-0017（留言與私有資料）、ADR-0021（單一內容寫入者）。

下文的 `$P` 是 Google Cloud 專案（`guthub-staging` 或 `guthub-prod`），`$REF` 是對應的 Supabase project ref，`$DB` 是擁有 `app` 表的連線字串。密碼放在 Secret Manager 的 `supabase-db-password`，不要貼進終端機歷史、issue 或 PR：

```sh
PW=$(gcloud secrets versions access latest --secret=supabase-db-password --project=$P)
DB="postgresql://postgres.$REF:${PW}@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
unset PW
```

## 會動到的東西

| 層 | 位置 | 退回方式 |
| --- | --- | --- |
| 內容（文獻、消息、主題） | 切換前在 repo 的 JSON，切換後在 Supabase `app` | `content_writer.py rollback`：先把資料庫內容匯出回 JSON |
| 留言、帳號、按讚、檢舉、審核紀錄 | 只在 Supabase | 不需要退回；網站退回時暫時看不到，資料不受影響 |
| API | Cloud Run `guthub-api` | 把流量切回前一個 revision |
| 網站 | Vercel 專案 `guthub` | Vercel 的 instant rollback；GitHub Pages 的現站整個過程都不關 |

## 備份與還原

- Supabase Pro 每天自動做一次實體備份，保留 7 天。PITR（任意時間點還原）沒有開，所以最多可能遺失近 24 小時的資料。查最近一次備份：`supabase backups list --project-ref $REF`。
- 還原演練：`SOURCE_URL="$DB" tools/restore-drill.sh`。腳本會匯出 `app` schema 和 `auth.users` 的 id、email，還原到臨時的 Postgres 17 容器，再逐表比對列數與內容雜湊，最後確認匿名留言的作者對應也一致。匯出檔含 email 與作者對應，只放在權限 700 的暫存目錄，結束時刪除。需要 Docker 與 `pg_dump` 17。
- 2026-11-17 在 staging 演練通過：14 張表全部一致（含測試用的署名與匿名留言、讚、檢舉、審核紀錄），`auth.users` 2 筆一致，匿名作者對應一致。
- 演練發現兩件事，腳本已處理：Supabase 在每個欄位加了 `pg_attver` 選項，一般 Postgres 不認得，會讓整張表建不起來，所以還原時把這些行濾掉；`pg_dump --schema` 加 `--table` 時只會留下 `--table` 的部分，所以 `auth.users` 另外用 `\copy` 匯出。
- 正式切換前，對 prod 再跑一次演練，並記下最近一次備份的時間。

## 暫停寫入（維護模式）

API 設了 `GUTHUB_WRITES_PAUSED=true` 時，所有 POST、PUT、PATCH、DELETE 都回 503 加 `Retry-After: 600`，讀取照常。網站看到這個組合會顯示「網站維護中，暫停留言、編輯與檢舉，閱讀不受影響」，讀者寫到一半的內容會留在輸入框。沒有 `Retry-After` 的 503 代表真的故障，網站顯示的是一般的錯誤訊息。

```sh
# 暫停（約 30 秒生效，Cloud Run 會建新 revision）
gcloud run services update guthub-api --project=$P --region=asia-northeast1 --update-env-vars=GUTHUB_WRITES_PAUSED=true
# 確認：應該是 503，且有 retry-after: 600
curl -si -X PUT https://<API 網址>/api/v1/me | grep -iE "^HTTP|retry-after"
# 恢復
gcloud run services update guthub-api --project=$P --region=asia-northeast1 --remove-env-vars=GUTHUB_WRITES_PAUSED
```

暫停期間不要合併任何會觸發部署 workflow 的 PR。部署用 `--set-env-vars` 整組重設環境變數，會把暫停一起解除。

## 切換順序

每一步完成後把結果（時間、SHA、revision 名稱）記在 F4 issue，rollback 時才知道要退回到哪裡。

1. **記下目前版本。** API revision：`gcloud run services describe guthub-api --project=$P --region=asia-northeast1 --format='value(status.latestReadyRevisionName)'`；網站：Vercel 專案目前的 production deployment；內容：`git rev-parse HEAD`。
2. **暫停寫入**（上一節）。
3. **停掉所有 JSON 寫入者**：`gh workflow disable paper-watch.yml`、`paper-accept.yml`、`unpublish.yml`。確認沒有還在跑的：`gh run list --status in_progress`。
4. **備份**：確認今天的 Supabase 備份已完成，並跑一次 `tools/restore-drill.sh`。
5. **匯入最終 JSON 並切換寫入者**：
   ```sh
   python import_content.py --database-url "$DB"
   python content_writer.py cutover --database-url "$DB"
   git add data/WRITER && git commit -m "chore(data): move the content writer to PostgreSQL (#79)"
   ```
   `cutover` 只在資料庫與 JSON 的 manifest 完全相同時才會切換，並把這份 manifest 存成匯入水位。`status` 子指令可以隨時查目前的寫入者與水位。
6. **部署 API 與工作排程**（prod 的部署 workflow，F4），記下新的 revision。
7. **網站**：Vercel 的 production 環境變數換成 prod 的值，接上 `guthub.tw`，設定 `GUTHUB_SITE_PUBLIC=1` 與 `GUTHUB_SITE_ORIGIN=https://guthub.tw`，重新部署。
8. **快取**：頁面是 ISR，最多 300 秒更新；重新部署會讓新版本立即生效。讀者瀏覽器裡的 Service Worker 快取（`guthub-public-v1`）只存公開頁面，下次連線時會改用新版內容，不需要手動清除。只有快取格式改變時才需要調高版本號。
9. **恢復寫入**，重新啟用改為讀寫資料庫的 workflow。
10. **驗收**：對正式網址跑 `tools/next-verify.js`、`tools/next-offline.js`、`tools/check_next_parity.py`，以及 `tools/next-auth.js`、`tools/next-comments.js`（這兩支會建立測試帳號，跑完照 F2 #77 的方式清掉）。

## Rollback

原則是**不丟資料**：切換後新發布的內容會先匯出回 JSON；留言只存在資料庫，不跟著退回。照下列順序做，可以只做到需要的那一步。

1. **暫停寫入。**
2. **API 有問題**：把流量切回切換前記下的 revision。
   ```sh
   gcloud run services update-traffic guthub-api --project=$P --region=asia-northeast1 --to-revisions=<舊 revision>=100
   ```
3. **網站有問題**：在 Vercel 對前一個 production deployment 做 instant rollback（`vercel rollback <deployment>` 或在 dashboard 操作）。最壞情況是把 `guthub.tw` 拿掉，讀者回到 GitHub Pages 的現站；現站沒有留言功能，留言暫時看不到，但都還在資料庫裡。
4. **內容寫入要退回 JSON**：
   ```sh
   python content_writer.py rollback --database-url "$DB"
   git add data/ docs/ && git commit -m "chore(data): return the content writer to JSON (#79)"
   ```
   `rollback` 會先把資料庫的內容與 Paper Watch 追蹤狀態匯出回 `data/`，再把 `data/WRITER` 改回 `json`，所以切換後發布的文獻不會遺失。之後重新啟用第 3 步停掉的 workflow。
5. **資料本身損壞**（最後手段）：用 Supabase dashboard 的備份還原。這會蓋掉備份時間之後的所有留言與帳號變更，執行前先用 `tools/restore-drill.sh` 的方式匯出一份目前的資料留存。
6. API 正常後**恢復寫入**，在 F4 issue 記錄原因與時間。

## 告警

用 `python3 tools/setup_monitoring.py $P <API 主機名稱> [通知管道 ...]` 建立，重複執行不會重複建立。

| 告警 | 觸發條件 | 先查什麼 |
| --- | --- | --- |
| GutHub API health check failing | `/api/v1/health` 每 5 分鐘檢查一次，超過一個區域失敗 | Cloud Run 的 `guthub-api` 日誌；health 在資料庫連不上時回 503，所以也要看 Supabase 狀態頁 |
| GutHub Cloud Run job failed | 任何 Cloud Run job 執行失敗（每日清除作者對應、Paper Watch） | `gcloud run jobs executions list --job=<job>` 和該次執行的日誌；Paper Watch 失敗最常見的原因是 Anthropic 額度用完（見 `docs/維運筆記.md`） |
| 預算 50%／90%／100% | 每月花費（staging 320 TWD、prod 960 TWD） | Billing 報表，看是哪個服務 |

告警建立時沒有掛通知管道，事件只會出現在 Cloud Console 的 Monitoring → Incidents。要收到 email，先在 Monitoring → Alerting → Edit notification channels 新增自己的 email，再把管道名稱（`projects/$P/notificationChannels/<id>`）加進兩條告警政策。預算告警會寄給帳單管理員，不需要另外設定。

2026-11-17 在 staging 驗證：用不存在的子指令讓 `purge-deleted-authors` 執行失敗一次，確認 job 告警會開事件。

Supabase 與 Vercel 的用量用各自的內建通知：Supabase Pro 預設開啟 spend cap，Vercel 在接近方案上限時寄信給帳號擁有者。
