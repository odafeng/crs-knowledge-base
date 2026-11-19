# 0026. 依藥物瀏覽文獻：手動維護藥物清單，比對試驗組合字串

**Status**: Accepted（2026-11-19 維護者提出需求；J1 #205）

## Context

網站原本只能依主題（biomarker 分組）找文獻。維護者希望也能依藥物找：點進 regorafenib，就看到所有和它有關的文獻，包括早期的 Phase 3、後來的 real-world 研究，以及把它當對照組的試驗。

站上沒有藥物欄位。藥名只出現在每篇文獻的 `regimen`（例如「FTD-TPI±bev/RAM vs fruquintinib vs Rego160 vs Rego80+」），以及 AI 速覽的標題與比較欄位（ADR-0025）。寫法不統一，同一個藥會有學名、縮寫，甚至夾著劑量的寫法，例如 regorafenib 也寫成 Rego160，trifluridine/tipiracil 也寫成 TAS-102 或 FTD-TPI，encorafenib + cetuximab 合寫成 EC。

## Decision

- `apps/web/src/lib/drugs.ts` 手動維護藥物清單，每種藥一列：學名、商品名、類別、別名。別名分兩種：學名與常見縮寫不分大小寫；EC、RAM、BOT、T-DXd 這類大寫縮寫只認大寫，以免普通單字被誤認。比對時藥名前後都不能緊接英文字母，所以「Rego160」算 regorafenib，「program」不會被當成 RAM。
- 文獻的 `regimen`、速覽標題或比較欄位提到某種藥，就歸到那種藥，不分它是試驗組、對照組，還是前線用過的藥。
- 只在網頁端比對，不改資料庫，也不改 API 或 Paper Watch。新頁面為 `/drugs/` 與 `/drugs/[slug]/`，首頁右欄列出篇數最多的 8 種藥，sitemap 收錄有文獻的藥物頁。

沒有選 AI 標註，原因是藥名本來就寫在文字裡，用規則比對就找得到，結果可以預測，也能寫測試。用 AI 標註還要多一個欄位和一道審核，每篇新文獻也都要花錢。

## Consequences

- 現有 53 篇中有 50 篇歸到至少一種藥。沒歸到的 3 篇只寫了類別（anti-EGFR、anti-PD-1）或是指引，本來就沒有指名哪個藥。
- 「有關」的範圍刻意放寬：FRESCO-2 只是收了用過 regorafenib 的病人，也會出現在 regorafenib 頁。對「找所有提到它的文獻」有利，但頁面上不區分角色。
- Paper Watch 收進一個清單裡沒有的新藥時，那篇不會出現在任何藥物頁，要有人把藥加進清單才會出現，目前沒有自動提醒。
- 清單是程式碼，加一個藥要開 PR。好處是每次修改都有測試把關，代價是要等部署才會生效。
- 化療骨幹（FOLFOX、FOLFIRI）沒有列入，因為幾乎每篇都有，放進去也篩不出東西。口服的 trifluridine/tipiracil 例外。

## References

- [J1 #205](https://github.com/odafeng/crs-knowledge-base/issues/205)
- [ADR-0025](0025-paper-summaries.md)
