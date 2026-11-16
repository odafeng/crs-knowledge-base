# Paper Watch 遷移 contract v1

此 contract 固定現行 Python 管線的發布行為，供 E2 的儲存 adapter 與 E4 的 ADK pilot 比對。實作仍使用 JSON，沒有啟用新 writer 或更換模型。

fixture 放在 [`tests/fixtures/pipeline-v1.json`](../tests/fixtures/pipeline-v1.json)，全部是合成資料，不能作臨床引用。`version` 是 fixture 格式版本；`today` 固定審核與追蹤日期。每個案例以淺層欄位取代 base；研究的 `entry` 只覆寫 `ai_suggested_js`，評論的 `model` 只覆寫模型回應欄位。陣列整組取代，不合併。

```bash
python -m pytest tests/test_pipeline_contract.py -q
```

測試執行真實 `run_pipeline`、分類門檻、commentary triage、provenance gate、writer、Issue payload、人工接受、撤下及 tracking。PubMed／RSS fetch 與模型輸出由 fixture 提供；GitHub Issue 與 LINE 通知以 mocks 接收呼叫，socket 連線被禁止。內容與 tracking 只寫入 pytest 暫存目錄，測試不需要 credentials，也不會呼叫付費模型。

| 邊界 | 固定的行為 |
|---|---|
| 一般研究 | 同 DOI／PMID 的 RSS 與 PubMed 候選只分類一次，優先使用 PubMed；同時帶 `Comment` 與原始研究 publication type 的候選仍進一般研究流程 |
| 自動發布 | 完整摘要、數字與原文出處、研究設計等檢查全數通過，保存 `source=abstract`、`review.status=auto` 與 AI 未審警語；保留已知 relations，丟棄不存在的 target |
| 保留審核 | 缺摘要、截斷摘要、錯誤數字、找不到引句、web-only 來源、研究設計不符、parse failure 與未分類均不得直接發布 |
| 人工接受 | 從 Issue 的嵌入 payload 發布，標為 `accepted`；未通過摘要 gate 的條目保留 `source=secondary`。沒有可發布 payload 的 parse failure／未分類案例不能接受 |
| 追蹤 | DOI 優先，缺 DOI 時使用 `pmid:<PMID>`；保存 PMID 以識別日後補 DOI 的同一文獻；同時保存 abstract ID。低分與 parse failure 仍追蹤；未分類與 commentary refusal 留待重試 |
| 研究 commentary | PubMed `CommentOn` 對應優先於模型選擇；有新數據、錯誤數字、錯誤 Phase 或只靠 AI 對應時送審核。未對應項目只追蹤；人工接受只收勾選項目 |
| 重跑與撤下 | 重複 paper writer 會拒絕；同一 commentary 不重複附加，也不藉重跑改寫既有審核標記。撤下移除詳細來源、相關 news 與反向 relations，保留人工整理條目 |
| dry-run | 不修改內容或 tracking；Issue／通知呼叫維持 `dry_run=True` |

`semantic-number-swap` 是刻意保留的限制案例：摘要寫樣本數 56、反應率 36%，條目卻寫反應率 56%。因為 56 確實出現在摘要與 evidence claim，現行 gate 仍會通過。這不是正確的臨床結果，也不是未來模型的合格答案；它用來防止把「數字可追溯」誤稱為「解讀正確」。未來若增加指標／組別檢查，需明確修改此預期並說明新的查核能力。

既有單元測試繼續涵蓋 XML 解析、來源格式與其他錯誤。這份 contract 未驗證真實供應商故障、GitHub 權限或部署後的快取失效；這些由 E3 與 F2 驗證，不能由這批 fixtures 推定通過。並行 writer 與資料庫 transaction 由 E2 的 `tests/test_content_writer.py` 驗證：資料庫模式跑的是同一套 `publish.py`，見 [ADR-0021](../docs/adr/0021-single-content-writer-and-cutover.md)。

相關決策：[ADR-0013](../docs/adr/0013-gated-auto-publish.md)、[ADR-0018](../docs/adr/0018-python-pipeline-and-adk.md)。工作與後續討論以 [E1 #72](https://github.com/odafeng/crs-knowledge-base/issues/72) 為準。
