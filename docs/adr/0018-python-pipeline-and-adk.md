# 0018. 保留 Python 文獻管線，獨立決定 ADK 導入

**Status**: Accepted（2026-11-16 維護者於 [E4 #74](https://github.com/odafeng/crs-knowledge-base/issues/74) 選擇單一主題 ADK pilot；既有發布規則仍依 ADR-0013）

## Context

目前七個 topic agents 使用 Python 呼叫模型與 PubMed 工具。管線已處理 DOI／PMID 去重、研究 commentary 分流、數字來源與研究設計檢查、人工接受、撤下與追蹤資料。

網站改用 React、資料改放 PostgreSQL，都不直接要求更換 agent framework。Google ADK 提供工具、agent 協作、流程與評估能力，可能適合後續擴展，但目前沒有已確認必須靠 ADK 才能解決的缺口。

## Decision

維護者選擇先做單一主題的 ADK pilot，MVP 的 Paper Watch 繼續使用現有 Python agents。2026-11-17 維護者於 [E5 #90](https://github.com/odafeng/crs-knowledge-base/issues/90) 確認：pilot 主題為 `mCRC-BRAF-V600E`，模型沿用現行管線的 Claude，只比較 framework 本身的差異。2026-11-20 維護者確定整個 pilot 的模型費用上限為 USD 20，到上限自動停止。pilot 結果不影響 MVP 的時程。

以下原則同時適用於 MVP 管線與 pilot：

- 建議 MVP 保留現有 Python agents。先以固定 fixtures 與 contract tests 保護目前行為，再改寫儲存 adapter、發布與排程整合。
- API 與 worker 共用來源查核及發布規則；查核邏輯不綁在 Next.js component、agent prompt 或特定雲端 SDK 裡。
- 保留 ADR-0013 的 provenance gate、AI 未審標示、人工接受／撤下與人工整理內容保護；既有研究設計、來源不完整及錯誤數字的回歸案例必須繼續通過。
- 舊 JSON writer 與新 PostgreSQL writer 的切換依 ADR-0016。接受／撤下事件與重試使用冪等識別，不產生第二條獨立內容權威。
- 掃描與分類作為排程／背景任務執行；保存單主題、人工觸發、dry-run、concurrency、timeout、重試及用量上限。執行環境依 ADR-0016 為 Cloud Run。
- 排程改造前先保留目前一般與會議季行為。測試不得發送真實通知或無限制呼叫付費模型。
- 若決定做 ADK pilot，只遷移一個有明確用途的流程，用同一批 fixtures 比較來源／數字正確性、gate 結果、人工介入、費用與耗時，先寫通過及退出條件。
- ADK 可以搭配不同模型與儲存服務，採用它不等於同時改用 Gemini 或 Cloud SQL。更換模型、公開 AI 問答或自動寫新聞稿，需各自有需求與驗收，不能隨 framework 遷移一併加入。
- 網站與留言的 MVP 不依賴 ADK 決策完成；未核准 pilot 前不預建全面 agent 重寫工作。

## Consequences

- 網站互動、資料庫遷移與 agent 改造可以分別驗收，來源查核不因 framework 更換而失去保護。
- 保留既有 Python 行為能降低同時更換多層造成的定位成本，但現有 agent loop 的維護責任也繼續存在。
- 若 ADK 的流程、觀測與評估能力確有幫助，pilot 可提供比較證據；同時需要額外測試與整合成本。
- 發布 adapter 與單一 writer 切換仍可能失敗，必須測試並行、重試、部分失敗及撤下後的快取一致性。
- provenance gate 檢查可追溯來源與數字，無法保證醫學解讀正確；保留揭露與人工介入能力。

## References

- [E1 #72：遷移 contract tests](https://github.com/odafeng/crs-knowledge-base/issues/72)
- [Paper Watch 遷移 contract v1](../../contracts/pipeline-migration.md)：合成 fixtures、發布／審核／撤下與 tracking 的比對邊界；未改變既有 gate。
- [E2 #73：發布／撤下 adapter](https://github.com/odafeng/crs-knowledge-base/issues/73)
- [E3 #76：worker 部署](https://github.com/odafeng/crs-knowledge-base/issues/76)
- [E4 #74：ADK 決策](https://github.com/odafeng/crs-knowledge-base/issues/74)
- [ADR-0013](0013-gated-auto-publish.md)
- [ADR-0016](0016-api-data-cloud-boundaries.md)
- [ADK 官方文件](https://adk.dev/)
