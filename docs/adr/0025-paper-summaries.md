# 0025. 文獻頁加 AI 撰寫的中文速覽，數字必須追得到原文

**Status**: Accepted（2026-11-18 維護者決定：AI 撰寫＋數字比對，標 AI 未審；Job I，I1 #190、I2 #191）

## Context

維護者看單篇文獻頁，覺得「很難一眼看懂那篇文章在幹嘛」，而且認為問題出在內容，不在版面。

文獻條目原本只有給已經懂的人看的短欄位：`regimen`（例如「EC+mFOLFOX6 vs SOC (1L)」）、英文縮寫的 `result`、一句口號式的 `bottomLine`。53 篇裡 39 篇是人工整理，`detail_html` 多半是英文摘要原文。頁面上沒有任何一處告訴讀者：這篇在問什麼、收了誰、比什麼、結果如何、要小心什麼。這些內容既不存在，版面再改也變不出來。

一篇一篇人工補寫，53 篇要花維護者很多時間，之後每篇新文獻也得補。

## Decision

每篇文獻加一份中文速覽，存在 `papers.json` 條目的 `summary`（資料庫 `app.papers.summary`，jsonb）：標題（試驗＋族群＋比較）、一句話結論、臨床問題、病人、比較、2–4 點主要結果、臨床意義、1–3 點限制，加上產生的模型、日期與 `reviewedAt`。

- **由 AI 寫**：`scripts/paper_summary.py` 依 DOI 取 PubMed 摘要，請 Claude（與 Paper Watch 同一個模型）依摘要與既有條目寫成 JSON。
- **數字必須追得到原文**：速覽裡的每個數字都要出現在摘要或已有的條目欄位，否則不寫入。規則與自動發布的 provenance gate（ADR-0013）相同：模型自己報告的出處不算數。形狀與長度由 `scripts/validate.py` 檢查。
- **標 AI 未審**：寫入時 `reviewedAt` 為 null。管理者在待審清單按「標為已審」時，文獻與速覽一起確認；人工整理的文獻若只有速覽待審，按鈕只確認速覽。
- **台灣核准與給付不交給 AI**：頁面直接引用主題的治療卡片，那些資料已逐條查核過健保與 TFDA 原文。
- **經由唯一的內容寫入者寫入**（ADR-0021）：和 Paper Watch 走同一個 `content_session`，拿同一把鎖、在交易裡寫入、記一筆 `summarize` 事件。因為每次寫入都會匯出再匯入整個知識庫，速覽必須是 `papers.json` 的正式欄位，否則下一次 Paper Watch 寫入就會把它蓋掉。

## Consequences

- 讀者打開文獻頁，第一眼就有中文的問題、族群、比較與結果；英文原文摘要退到下面。
- 數字比對只能擋住「原文沒有的數字」，擋不住「數字對、但歸錯組別或解讀錯誤」。所以速覽一律先標 AI 未審，靠維護者在待審清單確認，53 篇回填後待審清單會一次多出幾十筆。
- 沒有 DOI 或 PubMed 沒有摘要的文獻（目前 3 篇沒有 DOI）寫不出速覽，頁面沿用原本的欄位。
- 每篇要呼叫一次 Claude，回填 53 篇與之後每篇新文獻都會產生 API 費用（每篇約幾分錢），與 Paper Watch 共用同一把金鑰與帳單。
- 只有新增，沒有自動重寫：已有速覽的文獻不會被覆蓋，要重寫得加 `--redo`。文獻內容更新後，速覽可能過時，目前沒有自動偵測。

## References

- [I1 #190](https://github.com/odafeng/crs-knowledge-base/issues/190)、[I2 #191](https://github.com/odafeng/crs-knowledge-base/issues/191)、[I3 #192](https://github.com/odafeng/crs-knowledge-base/issues/192)
- [ADR-0013](0013-gated-auto-publish.md)、[ADR-0021](0021-single-content-writer-and-cutover.md)
