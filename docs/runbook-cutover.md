# 正式切換、rollback 與告警 runbook

對應 F3 #78。寫給另一位維護者：照順序執行就能完成切換或退回，不需要先讀完所有 ADR。背景與取捨見 ADR-0016（環境）、ADR-0017（留言與私有資料）、ADR-0021（單一內容寫入者）。

下文的 `$P` 是 Google Cloud 專案（`guthub-staging` 或 `guthub-prod`），`$REF` 是對應的 Supabase project ref，`$POOLER` 是該專案的連線池主機，`$DB` 是擁有 `app` 表的連線字串。兩個專案在不同的連線池主機上，用錯會出現 `tenant/user ... not found`：

| 環境 | `$P` | `$REF` | `$POOLER` |
|---|---|---|---|
| staging | `guthub-staging` | `dlfhqneoqxlelczqcxif` | `aws-0-ap-northeast-1.pooler.supabase.com` |
| 正式 | `guthub-prod` | `pcmxouxeaoqvvegbclfg` | `aws-1-ap-northeast-1.pooler.supabase.com` |

密碼放在 Secret Manager 的 `supabase-db-password`，不要貼進終端機歷史、issue 或 PR：

```sh
PW=$(gcloud secrets versions access latest --secret=supabase-db-password --project=$P)
DB="postgresql://postgres.$REF:${PW}@$POOLER:5432/postgres?sslmode=require"
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

## 正式環境部署（Deploy production）

正式環境只能手動部署：到 GitHub Actions 選「Deploy production」，在 `main` 上執行，確認欄位輸入 `production`；或執行 `gh workflow run deploy-prod.yml --ref main -f confirm=production`。步驟和 staging 完全相同（兩邊都呼叫 `.github/workflows/deploy.yml`）：套用 migration、建置映像、部署 API、每日清除 job，以及各自開關控制的 job。

各 job 的開關（`LINE_ENABLED`、`PUSH_ENABLED`、`PAPER_WATCH_ENABLED`、`REGULATORY_WATCH_ENABLED`）與 `WEB_ORIGINS` 都設在 **GitHub environment**（Settings → Environments → `production` 或 `staging`），不要設成 repository 變數，否則兩個環境會一起開。

第一次部署前，維護者要先做一次（agent 沒有權限改正式環境的 IAM）：

```sh
gcloud projects add-iam-policy-binding guthub-prod --condition=None \
  --member=serviceAccount:deployer@guthub-prod.iam.gserviceaccount.com --role=roles/cloudscheduler.admin
gcloud secrets add-iam-policy-binding supabase-db-password --project=guthub-prod \
  --member=serviceAccount:deployer@guthub-prod.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
```

再到 Settings → Environments → `production` 加上變數 `WEB_ORIGINS`（例如 `["https://guthub.tw"]`）。這個 environment 已經設定好（2026-11-17）：每次部署都要維護者核准，而且只允許從 `main` 部署。這兩條規則存在 GitHub 設定裡，改 workflow 檔案也繞不過。

workflow 裡的 `if: github.ref == 'refs/heads/main'` 只是方便，真正的限制有三層：上面的 environment 規則；prod 身分聯合只接受 `refs/heads/main`；以及建議再加上只接受 `production` environment 發出的 token（維護者執行一次）：

```sh
gcloud iam workload-identity-pools providers update-oidc github-oidc --project=guthub-prod \
  --location=global --workload-identity-pool=github \
  --attribute-condition="assertion.repository=='odafeng/crs-knowledge-base' && assertion.ref=='refs/heads/main' && assertion.environment=='production'"
```

## 切換後的內容寫入（Paper Watch、接受、撤下）

切換後只有資料庫能寫內容，GitHub Actions 上的 `paper-watch.yml` 會拒絕寫入，`paper-accept.yml` 與 `unpublish.yml` 也不能再 commit JSON。三件事改在 guthub-prod 的 Cloud Run 執行：

- **Paper Watch**：`paper-watch` job，每天 16:00（台灣時間）執行完整掃描（會議季時一併掃描會議摘要）。
- **接受、撤下**：兩個 workflow 只負責啟動 `content-requests` job，不帶參數。job 自己讀 issue：開著且標了 `accepted` 的待審 issue（由 github-actions 或 repo 擁有者開的）就發布、回覆、關閉；Unpublish workflow 開的 `[撤下] <目標>` issue（標 `unpublish-request`）就撤下、回覆、關閉。
- **網站上的審閱按鈕**（E6 #159）：管理者在「AI 未審」的頁面按「標為已審」或「撤下」，API 記下請求並啟動同一個 job。部署 workflow 會讓 `api-runtime` 可以啟動它，不需要另外設定。
- 資料庫密碼一直留在 Secret Manager。GitHub 用 `content` environment 換到 `content-trigger@` 的身分，這個身分只能啟動 `content-requests` 這一個 job，不能帶參數，也不能部署。

切換前由維護者做一次（agent 沒有權限改正式環境的 IAM 與祕密）：

1. **祕密**，都存在 guthub-prod，並讓 `worker-runtime` 可以讀：
   - `guthub-content-database-url`：用 prod 的 `supabase-db-password` 組成，主機是 aws-1（見最上面的表）。
   - `anthropic-api-key`。
   - `paper-watch-github-token`：只授權本 repo、Issues 可讀寫的 fine-grained token，**由 repo 擁有者建立**。接受流程只信任 github-actions 或 repo 擁有者開的 issue，token 換成別人的，它開的待審 issue 就無法接受。
   - 選用：給維護者自己的 LINE 通知（不是 GutHub 讀者帳號）放 `paper-watch-line-token` 與 `paper-watch-line-user-id`，再在 `production` environment 設 `PAPER_WATCH_LINE_NOTIFY=true`。
   ```sh
   for s in guthub-content-database-url anthropic-api-key paper-watch-github-token; do
     gcloud secrets add-iam-policy-binding $s --project=guthub-prod \
       --member=serviceAccount:worker-runtime@guthub-prod.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   done
   ```
2. **身分**，順序不能換：先把 `deployer` 限定在 `production` environment，再放寬身分聯合的條件。反過來做的話，`content` environment 的 token 也能部署，等於繞過部署核准。
   ```sh
   POOL=projects/392767072259/locations/global/workloadIdentityPools/github
   gcloud iam workload-identity-pools providers update-oidc github-oidc --project=guthub-prod \
     --location=global --workload-identity-pool=github \
     --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.environment=assertion.environment"
   gcloud iam service-accounts add-iam-policy-binding deployer@guthub-prod.iam.gserviceaccount.com --project=guthub-prod \
     --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/$POOL/attribute.environment/production"
   gcloud iam service-accounts remove-iam-policy-binding deployer@guthub-prod.iam.gserviceaccount.com --project=guthub-prod \
     --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/$POOL/attribute.repository/odafeng/crs-knowledge-base"
   gcloud iam service-accounts create content-trigger --project=guthub-prod \
     --display-name="GitHub: start the content-requests job"
   gcloud iam service-accounts add-iam-policy-binding content-trigger@guthub-prod.iam.gserviceaccount.com --project=guthub-prod \
     --role=roles/iam.workloadIdentityUser --member="principalSet://iam.googleapis.com/$POOL/attribute.environment/content"
   gcloud iam workload-identity-pools providers update-oidc github-oidc --project=guthub-prod \
     --location=global --workload-identity-pool=github \
     --attribute-condition="assertion.repository=='odafeng/crs-knowledge-base' && assertion.ref=='refs/heads/main' && assertion.environment in ['production', 'content']"
   ```
   `content-trigger` 不在專案層級拿任何角色；部署 workflow 只在 `content-requests` 這個 job 上給它 `run.invoker`。
3. GitHub `content` environment（只允許 `main`、不需核准）已由 agent 建立。在 `production` environment 設 `CONTENT_REQUESTS_ENABLED=true`，執行一次 Deploy production，建立 `content-requests` job。
4. **`PAPER_WATCH_ENABLED` 等到切換第 6 步才設。** 切換前就開的話，Cloud Run 和 GitHub Actions 會同時跑 Paper Watch，重複開 issue，模型也會付兩次費。

## 切換順序

每一步完成後把結果（時間、SHA、revision 名稱）記在 F4 issue，rollback 時才知道要退回到哪裡。

0. **切換前先部署一次正式環境**（上一節）。這時 guthub.tw 還沒指過來，讀者看不到；目的是讓 prod 資料庫先有最新的資料表，第 5 步才能匯入，第 2 步也才有 API 可以暫停。

1. **記下目前版本。** API revision：`gcloud run services describe guthub-api --project=$P --region=asia-northeast1 --format='value(status.latestReadyRevisionName)'`；網站：Vercel 專案目前的 production deployment；內容：`git rev-parse HEAD`。
2. **暫停寫入**（上一節）。
3. **停掉所有 JSON 寫入者**：`gh workflow disable paper-watch.yml`、`paper-accept.yml`、`unpublish.yml`。確認沒有還在跑的：`gh run list --status in_progress`。`paper-watch.yml` 從此不再啟用，由 Cloud Run 的 `paper-watch` job 取代。
4. **備份**：確認今天的 Supabase 備份已完成，並跑一次 `tools/restore-drill.sh`。
5. **匯入最終 JSON 並切換寫入者**：
   ```sh
   python import_content.py --database-url "$DB"
   python content_writer.py cutover --database-url "$DB"
   git add data/WRITER && git commit -m "chore(data): move the content writer to PostgreSQL (#79)"
   ```
   `cutover` 只在資料庫與 JSON 的 manifest 完全相同時才會切換，並把這份 manifest 存成匯入水位。`status` 子指令可以隨時查目前的寫入者與水位。
6. **啟用 Paper Watch 並部署**：在 `production` environment 設 `PAPER_WATCH_ENABLED=true`，執行 Deploy production，確認 `paper-watch` job 與 `paper-watch-daily` 排程已建立，並記下新的 API revision。注意：部署會整組重設環境變數，等於提前解除第 2 步的寫入暫停。
7. **網站**：Vercel 有兩個專案，和 Google Cloud 一樣分開。`guthub` 是測試站（`guthub-lyart.vercel.app`，接 staging），維持不動；`guthub-prod` 是正式站（2026-11-17 建立），只在 `main` 更新時建置，production 變數指向 prod API 與 prod Supabase，並設定 `GUTHUB_SITE_PUBLIC=1`、`GUTHUB_SITE_ORIGIN=https://guthub.tw`。`guthub.tw` 與 `www.guthub.tw` 已加進 `guthub-prod`。這一步只剩 DNS：在 Cloudflare 把 `@` 和 `www` 改成 CNAME `23baa30a7fde215f.vercel-dns-017.com`，並關掉 proxy（灰色雲朵），讓 Vercel 簽發憑證。同時確認 prod Supabase 的 Authentication → URL Configuration：Site URL 是 `https://guthub.tw`，Redirect URLs 包含 `https://guthub.tw/auth/callback/`。
8. **快取**：公開內容與詳情頁 ISR TTL 為 3600 秒（1 小時，K3 #253），並透過 `POST /api/revalidate` 支援即時失效；啟用方式為在 Vercel 設定 `GUTHUB_REVALIDATE_SECRET`、在 Secret Manager 建立同值的 `revalidate-secret`（授權 `worker-runtime` 讀取），並在 GitHub `production` environment 設 `REVALIDATE_ENABLED=true` 後重新執行 Deploy production。讀者瀏覽器裡的 Service Worker 快取（`guthub-public-v1`）只存公開頁面，下次連線時會改用新版內容，不需要手動清除。只有快取格式改變時才需要調高版本號。
9. **恢復寫入**，重新啟用 `paper-accept.yml` 與 `unpublish.yml`。它們讀到 `data/WRITER=postgres` 後只會啟動 `content-requests` job。
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
   `rollback` 會先把資料庫的內容與 Paper Watch 追蹤狀態匯出回 `data/`，再把 `data/WRITER` 改回 `json`，所以切換後發布的文獻不會遺失。接著暫停 Cloud Run 的 Paper Watch（`gcloud scheduler jobs pause paper-watch-daily --project=$P --location=asia-northeast1`），並刪掉 `production` environment 的 `PAPER_WATCH_ENABLED`，再重新啟用第 3 步停掉的 workflow，避免兩邊同時跑。
5. **資料本身損壞**（最後手段）：用 Supabase dashboard 的備份還原。這會蓋掉備份時間之後的所有留言與帳號變更，執行前先用 `tools/restore-drill.sh` 的方式匯出一份目前的資料留存。
6. API 正常後**恢復寫入**，在 F4 issue 記錄原因與時間。

## 啟用推播（選擇性）

推播預設關閉（ADR-0023）。要在某個環境開啟：

1. 產生一組 VAPID 金鑰：`python -m push.keys`。印出的私鑰只存進 Secret Manager，不要貼到其他地方：
   ```sh
   printf %s '<私鑰>' | gcloud secrets create vapid-private-key --project=$P --data-file=-
   gcloud secrets add-iam-policy-binding vapid-private-key --project=$P \
     --member=serviceAccount:api-runtime@$P.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```
2. 公鑰設成 Vercel 的 `NEXT_PUBLIC_PUSH_PUBLIC_KEY`（`--no-sensitive`），重新部署網站，訂閱框就會出現推播按鈕。
3. 在 GitHub environment 設定 `PUSH_ENABLED=true`，再部署一次。部署 workflow 會建立 `announce-news` job，以及每 30 分鐘執行一次的排程。
4. 用自己的手機或電腦開啟推播，發布一則新消息，確認 30 分鐘內收到通知。

Cloud Scheduler 每個帳單帳戶有 3 個免費排程，超過後每個每月 USD 0.10；Secret Manager 超過免費版本數後，每個版本每月 USD 0.06。

## 啟用 LINE 每日推送（G3 #114）

方案、頻率與帳號已在 ADR-0022 決定：免費的輕用量、有新內容才推、另外建立給讀者的 GutHub 官方帳號。

1. 在 LINE Official Account Manager 建立「GutHub」官方帳號，到「設定 → Messaging API」啟用，再到 LINE Developers console 的該 channel 發行 long-lived channel access token。
2. 把 token 存進 Secret Manager，並讓 `api-runtime` 可以讀取：
   ```sh
   printf %s '<token>' | gcloud secrets create line-channel-access-token --project=$P --data-file=-
   gcloud secrets add-iam-policy-binding line-channel-access-token --project=$P \
     --member=serviceAccount:api-runtime@$P.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```
3. 先乾跑看訊息內容，不會發送：`gcloud run jobs execute line-daily --args=-m,guthub_api.maintenance,line-daily,--dry-run`（job 部署後）或在本機執行 `python -m guthub_api.maintenance line-daily --dry-run --date <有新內容的日期>`。
4. **guthub.tw 上線後**，在 GitHub environment `production`（不是 repository 變數）設定 `LINE_ENABLED=true`，再執行一次 Deploy production。會建立 `line-daily` job 與每天 07:00 的排程。token 只放在 `guthub-prod`，staging 沒有，所以不要在 `staging` environment 開啟。

broadcast 會送給這個帳號的**所有**追蹤者，所以只在給讀者用的帳號啟用；不要把 Paper Watch 通知維護者用的既有帳號 token 放進來。訊息按收件人計算，超過每月額度時 LINE 回 429，job 失敗告警會通知。

## 告警

用 `python3 tools/setup_monitoring.py $P <API 主機名稱> --email <維護者信箱>` 建立，重複執行不會重複建立。`--email` 會找出或建立該信箱的通知管道，並補進已存在的告警政策；政策上原有的管道會保留。

| 告警 | 觸發條件 | 先查什麼 |
| --- | --- | --- |
| GutHub API health check failing | `/api/v1/health` 每 5 分鐘檢查一次，超過一個區域失敗 | Cloud Run 的 `guthub-api` 日誌；health 在資料庫連不上時回 503，所以也要看 Supabase 狀態頁 |
| GutHub Cloud Run job failed | 任何 Cloud Run job 執行失敗（每日清除作者對應、Paper Watch） | `gcloud run jobs executions list --job=<job>` 和該次執行的日誌；Paper Watch 失敗最常見的原因是 Anthropic 額度用完（見 `docs/維運筆記.md`） |
| regulatory-watch 開出的 issue（標題以「[G5 監測]」開頭） | 健保給付規定有新版、章節消失，或 TFDA 許可證在卡片查核日之後異動、註銷 | 對照 issue 裡的新條文或適應症全文更新卡片；job 不會自動改卡片 |
| 預算 50%／90%／100% | 每月花費（staging 320 TWD、prod 960 TWD） | Billing 報表，看是哪個服務 |

2026-11-21 起 staging 與 prod 的兩條告警都掛上維護者的 email 管道（prod 在這天才第一次建立 uptime check 與告警）。沒帶 `--email` 也沒給管道時，事件只會出現在 Cloud Console 的 Monitoring → Incidents。換維護者時，用新信箱再跑一次 `--email`，再到 Monitoring → Alerting → Edit notification channels 移除舊的。預算告警會寄給帳單管理員，不需要另外設定。

2026-11-17 在 staging 驗證：用不存在的子指令讓 `purge-deleted-authors` 執行失敗一次，幾分鐘後 `run.googleapis.com/job/completed_execution_count`（`result=failed`）記到 1，這正是 job 告警的條件。2026-11-21 掛上 email 管道後，用同樣方式（`--args=-m,guthub_api.maintenance,no-such-command`）再讓它失敗一次，測試通知是否寄達。

同一天也在 staging 實際打開與關閉暫停開關：暫停時寫入回 503 加 `retry-after: 600`，CORS 標頭照常並公開 `Retry-After`，讀取維持 200；恢復後寫入回到正常的 401（未登入）。

Supabase 與 Vercel 的用量用各自的內建通知：Supabase Pro 預設開啟 spend cap，Vercel 在接近方案上限時寄信給帳號擁有者。
