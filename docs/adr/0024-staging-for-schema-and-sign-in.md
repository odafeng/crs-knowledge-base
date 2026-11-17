# 0024. staging 只用來預演資料庫、登入與部署的變更

**Status**: Accepted（2026-11-18 維護者決定；修訂 ADR-0016 的環境用法）

## Context

ADR-0016 與 F1 #75 建立了兩套彼此隔離的環境：staging（`guthub-staging`、Supabase `dlfhqneoqxlelczqcxif`、Vercel `guthub`）與 production（`guthub-prod`、Supabase `pcmxouxeaoqvvegbclfg`、Vercel `guthub-prod`）。原本只要 main 上的 API、排程、腳本或資料庫有變動，就會自動部署到 staging。

實際用下來，staging 對一人維護的網站負擔偏重：每個新功能的祕密、變數與外部帳號都要設兩次（OAuth client、Voyage key、LINE、推播、Paper Watch）。結果 staging 還是落後正式站，例如沒有 Voyage key、沒有開 Paper Watch。

不過，staging 確實擋下過一次事故：`supabase config push` 在非互動模式下直接把整份設定推上去，關掉了 MFA 等設定。當時推的是 staging，正式站沒有受影響。staging 的價值集中在「出錯後難以復原」的變更上。

## Decision

- staging 只預演四類變更，main 上有這些變更就自動部署到 staging：
  - 資料庫 migration（`supabase/migrations/`）
  - Supabase 設定（`supabase/config.toml`）
  - 登入 token 的驗證（`apps/api/src/guthub_api/auth.py`）
  - 部署流程本身（`deploy.yml`、`deploy-staging.yml`）
- 其他變更（功能、頁面、排程、內容處理）通過 CI 後直接部署正式站。CI 會對本機 Supabase 跑 API、資料庫與 E2E 測試。
- Deploy production 先檢查一次：自上次成功的正式部署以來，若有上述四類變更，最近一次成功的 staging 部署必須包含它，否則拒絕部署。
- staging 不必和正式站功能一致。新功能的祕密與開關變數只設在 production；staging 沒有的功能維持關閉，相關程式碼照常部署。
- Vercel 的 `guthub` 專案照舊建置每個 PR 的預覽網址（連 staging API），不需要另外維護。

## Consequences

- 新功能不必在 staging 補齊設定，維護者要做的事減少約一半。
- 資料庫與登入的變更仍會先在真的 Supabase 專案上跑過一次。本機 Supabase 和託管版有差異（擴充套件、連線池、Auth 設定），這一步仍然必要。
- 一般功能失去「上線前在真實雲端環境看一眼」的機會。例如 Cloud Run 的環境變數、祕密權限、外部服務連線出錯，要到正式站才會發現。這類錯誤通常只影響單一功能，且多半有開關可以關掉。
- staging 的功能會越來越落後正式站，不能再拿它展示完整網站。
- 正式部署前的檢查依賴 GitHub Actions 的執行紀錄。紀錄被刪除，或 staging 用手動執行部署了別的分支，判斷就可能不準。staging 只接受 main，風險有限。
