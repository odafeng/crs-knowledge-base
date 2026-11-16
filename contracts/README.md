# GutHub API contract

`openapi.yaml` 是前後端共用的 OpenAPI 3.1 contract，版本為 `0.1.0`。目前還沒有對應的 API server。Auth 採 Supabase、API 部署於 Cloud Run（ADR-0016）；留言需登入，可選對其他讀者匿名，不開放免註冊（ADR-0017）。本契約固定資料格式與可見性。

API 使用 `/api/v1`。前端可從這份檔案產生 TypeScript types；FastAPI 實作需通過相同 fixtures。檢查方式：

```bash
pip install -r scripts/requirements.txt -r requirements-site.txt -r requirements-dev.txt
python -m pytest tests/test_api_contract.py -q
```

## 識別與內容對應

- `Paper.id` 保留來源 ID 的大小寫及底線；`slug` 延用現有小寫／底線轉連字號規則，公開頁面仍為 `/papers/<slug>/`。
- `topic` 使用目前 JSON 的主題 key。`relations.targetId` 仍指向 paper ID，不能改成 slug 或資料庫內部流水號。
- 保留 `source`、`reviewedAt`、`review`、DOI、研究 `commentary` 及完整 `detailHtml`。沒有 `review` 的既有人工整理條目仍可表示；人工接受也不代表數字已核對全文。
- 原始 `file` 是匯入與稽核要保留的來源路徑，公開 DTO 改為提供詳細內容，不要求瀏覽器開啟本機檔案。
- 消息保留 headline phrases、圖表、本文與 AI 未審狀態。新聞的發表日期在頂層 `publishedAt`，現有只含 status 的 news review 也可匯入。
- 治療／監管卡片與 robotic timeline/cards 保留既有內容及來源。HTML 必須由 API 清理後提供；留言使用純文字，不接受以 HTML 取代內容。

## 讀取與寫入邊界

| 路徑 | 用途與可見性 |
|---|---|
| `/papers`、`/papers/{paperId}` | 公開文獻與完整證據 |
| `/news`、`/news/{newsId}` | 公開消息，保留未審狀態供 noindex 使用 |
| `/topics`、`/topics/{topicKey}` | 主題、治療卡片及 robotic sections |
| `/search` | 文獻／消息搜尋；回傳可開啟的網站 path |
| `/papers/{paperId}/comments` | GET 只列已公開留言；POST 驗證 session 與政策 |
| `/me` | 本人的顯示名稱與管理角色；PUT 設定顯示名稱，第一次設定時建立帳號（D1） |
| `/me/comments` | 本人的留言與審核狀態，私有回應 |
| `/comments/{commentId}` | 本人修改／刪除；以伺服器查核 ownership |
| `/comments/{commentId}/reports` | 經驗證 session 提交檢舉 |
| `/comments/{commentId}/likes`、`/me/likes` | 按讚與取消；公開只有讚數，誰按讚只有本人看得到自己的（H1） |
| `/admin/comments`、`/admin/comments/{commentId}` | 具 `comments:moderate` permission 的管理流程：佇列、公開／隱藏（必填原因） |
| `/admin/comments/{commentId}/author` | 查看作者；原因必填，每次查閱都寫入稽核紀錄 |

所有 mutation、本人資料及管理回應使用 `Cache-Control: private, no-store`。權限由伺服器驗證，不能因持有一般 session 就操作他人資料。MVP 不啟用 Supabase 匿名登入；伺服器以 claims 拒絕匿名 session 的寫入。

公開 `PublicComment` 不包含 account ID、作者對應、email 或管理 metadata。`anonymous=true` 時 `displayName` 必須為 null，畫面自行顯示匿名標籤；具名時僅提供可公開的顯示名稱。本人操作使用私有 `/me/comments`，不靠在公開列表暴露作者 ID 來判斷 ownership。公開 DTO 的未列出欄位均不接受。

研究 `ResearchCommentary` 與讀者留言使用不同 schema。讀者不能在留言建立請求指定 `authorId`、發布／審核狀態或文獻 review。資料庫與 API 的實際權限仍須在 B3/D2 做 integration tests，schema 驗證本身不等於已實作匿名隔離。

## 分頁與錯誤

列表使用 `limit` 與 opaque `cursor`，回傳 `items`、`nextCursor`；最後一頁為 null。搜尋需有至少兩個字元。讀者留言上限 2000 字元（檢舉理由 1000 字元），每帳號 10 分鐘 5 則、每日 50 則；帳號首則留言為 `pending`，之後直接 `published`（ADR-0017）。留言是純文字，只允許換行與 tab 兩種控制字元。作者修改不會改變審核狀態。

錯誤固定為 `error: {code, message, requestId}`，涵蓋 401、403、404、409、422、429、503。錯誤回應不可包含 token、私有作者資訊、資料庫錯誤或來源全文。429 的限制由服務端實作，不能只在 UI 阻止送出。

文獻發布／人工接受／撤下仍由受控的 pipeline adapter 處理，這份契約沒有新增公開的文獻寫入入口；單一 writer 的切換依 E2。

相關決策：[ADR-0016](../docs/adr/0016-api-data-cloud-boundaries.md)、[ADR-0017](../docs/adr/0017-comments-and-anonymous-identity.md)、[B1 #58](https://github.com/odafeng/crs-knowledge-base/issues/58)。
