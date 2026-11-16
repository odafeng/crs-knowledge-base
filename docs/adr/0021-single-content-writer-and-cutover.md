# 0021. 文獻內容同一時間只有一個寫入端，切換以資料庫比對 JSON 為準

**Status**: Accepted（E2 #73；依 ADR-0013 的發布規則與 ADR-0016 的單一權威）

## Context

Paper Watch 的自動發布、人工接受與撤下（ADR-0013）都寫 `data/papers.json`、`data/news.json` 與 `docs/`，由 GitHub Actions commit 回 git。ADR-0016 決定 PostgreSQL 在正式切換後成為內容的唯一權威，JSON 若保留只能單向 export，不能讓 git 與資料庫各自接受寫入。

發布規則都寫在 `scripts/publish.py`：provenance gate 的結果怎麼寫成條目、`validate_data()`、人工整理條目不能撤下、撤下時一併移除相關消息與反向 relations。E1 的 contract tests 鎖住這些行為。若為資料庫另寫一套，兩邊遲早不一致。

B4 的匯入工具已能把 JSON 轉成資料表列，重跑會收斂到相同結果，來源裡消失的文獻與消息標成 withdrawn 而不刪除。

## Decision

- **同一套發布規則，換一個存放位置**。資料庫模式下（設定 `GUTHUB_CONTENT_DATABASE_URL`），每個發布、接受或撤下請求在一個交易裡執行：
  1. 先取得全域寫入鎖，把資料庫的公開內容匯出到暫存目錄，排成 repository 的檔案結構。
  2. 讓 `publish.py` 照舊修改並驗證這份檔案。
  3. 再用 B4 的 `build_rows`／`apply` 寫回。

  撤下的文獻因此變成 `withdrawn_at`，留言仍可對應。任何錯誤都會讓整個交易回復。
- **匯出必須可逆**：`export_kb` 匯出後再 `build_rows`，得到的 manifest 與原本 repository 完全相同。測試以真實知識庫驗證這一點，並確認匯出結果通過 `validate_data()`。
- **重試不重複**：每個請求以「動作、目標、workflow run ID」為 key 寫入 `app.publish_events`，和內容在同一個交易。同一個 run 重跑時找到這筆紀錄就停止，只回報第一次的結果。重複的文獻 ID 或 DOI 仍由 `validate_data()` 擋下。
- **並行寫入串行化**：交易一開始取得 `pg_advisory_xact_lock`，並鎖住 `app.content_writer` 那一列。後到的寫入端會等前一個 commit 後才匯出，所以看得到前一個寫入的內容，不會用舊資料覆蓋。測試在拿掉兩道鎖時會掉文獻，保留任一道就不會。
- **寫入端只有一個**：資料庫的 `app.content_writer` 與 repository 的 `data/WRITER` 記錄目前由誰寫入。JSON 模式下，`KB.save` 在 `data/WRITER` 不是 `json` 時拒絕寫入；資料庫模式與 `import_content.py` 都會先檢查資料表的狀態，各自只在 `postgres`／`json` 時執行。切換後再匯入 JSON 會被拒絕，所以 git 裡的舊內容不會蓋過資料庫的新寫入。
- **切換程序**（`content_writer.py`）：
  1. 停掉所有 JSON 寫入端（Paper Watch、accept、unpublish workflows）。
  2. 匯入最後一版 JSON。
  3. 執行 `cutover`。只有資料庫內容與 JSON 的 manifest 完全相同時才切換，並把這份 manifest 存成水位，同時把 `data/WRITER` 改成 `postgres`，需要 commit。
  4. `rollback` 先把資料庫內容匯出回 repository，再交還給 JSON。
  5. `export` 隨時可做單向匯出，供現行靜態網站或備份使用。
- 三個入口（`main.py`、`accept_issue.py`、`unpublish.py`）都改經 `content_session`。沒有設定資料庫時行為與原本相同，E1 的 contract tests 不需修改。

## Consequences

- 發布規則只有一份。資料庫模式與 JSON 模式跑的是同一段 `publish.py`，E1 的回歸案例同時保護兩邊。
- 每次寫入都會匯出並重寫全部內容，寫入量與知識庫大小成正比。目前約 50 篇文獻、每週幾次寫入，不成問題；內容大很多時要改成只寫變動的列。
- 匯出的詳細頁只保留網站實際讀取的內文。`rollback` 後，`docs/` 裡的頁面和原本的檔案不會逐位元相同（頁面外框、`<head>` 會不同），但網站顯示的內容相同。撤下文獻的舊檔案不會被刪除。
- `rollback` 之後，網站可能因為資料庫依年份與 ID 排序而改變同主題內文獻的檔案順序。
- 撤下後，公開 API 立即排除該文獻；Next.js 頁面要等 ISR 重新產生（最多 5 分鐘），讀者裝置上的離線副本要等下次同步（ADR-0019）。目前沒有主動清除 CDN 快取，F2 的 staging 驗收要量測實際延遲。
- 兩個旗標（`app.content_writer` 與 `data/WRITER`）要一致。切換時若只完成一半，例如資料庫已切換但 `data/WRITER` 尚未 commit，GitHub 上的 JSON workflow 仍可能寫入 git，而這些寫入不會進資料庫。所以第一步必須先停掉 workflows。
- Paper Watch 的追蹤紀錄（哪些 DOI 已處理）仍是 repository 裡的檔案，不在這次切換範圍。worker 部署（E3）時要一併決定放哪裡。
- 寫入端需要擁有內容資料表的資料庫角色（與匯入相同），`guthub_api` 不能寫內容。

## References

- [E2 #73](https://github.com/odafeng/crs-knowledge-base/issues/73)、[E1 contract](../../contracts/pipeline-migration.md)
- [ADR-0013](0013-gated-auto-publish.md)、[ADR-0016](0016-api-data-cloud-boundaries.md)、[ADR-0019](0019-nextjs-offline-sync-and-client-search.md)
