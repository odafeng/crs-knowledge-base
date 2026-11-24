# REVIEW — GutHub (`guthub.tw`) Launch Film

## Creative Calls
- **Chosen storyline**: Storyline A (**《開會前十分鐘：一條證據的旅程》**) — 92 s, 1920×1080, 30 fps (2760 frames), synced to the 7 Minimax-Speech-2.8HD voiceover slots (`vo-01`..`vo-07`).
- **Storylines not built**: Storyline B (single-frame Swiss editorial grid rebuild) and Storyline C (high-pressure 3-way split collapse); preserved in `STORYLINES.md` if you want to explore an alternative cut later.
- **Visual truth**: Every single colour token (`#f6f5f0`, `#0f1f44`, `#1a3a7e`, `#8f2542`, `#0b5d3c`, `#734604`, `#0f1217`), brand mark (`guthub-logo.png`), LINE OA vector QR (`line-oa-qr.svg`, `@742rxviu`), font (`archivo-latin.woff2`), trial figure (`NICHE-2`, `PARADIGM`, `FIRE-3`, `BREAKWATER`, `BEACON`, `AZUR-1`), DOI, and Taiwan NHI clause (`9.134`, `9.53 1.`, `9.27 1.(1)`, `9.69 1.(11)`) comes directly from `apps/web/` and `data/`.

## Measured vs. Visual Checks
- **Measured (`hyperframes check --json`)**:
  - `lint`: 0 errors
  - `runtime`: 0 errors, 0 warnings
  - `layout`: 0 errors, 0 warnings across all 9 sampled timestamps
  - `contrast`: 115 / 115 text checks passed (0 failures)
  - `craft`: 599 temporal samples, 0 `dead_stretch`, 0 `text_below_floor`, 0 `line_unread`
- **Visually inspected (`hyperframes snapshot --review` + targeted seam/beat pass)**:
  - Inspected all 14 beat frames, 360px phone legibility sheet, and scene seams; caught and fixed:
    1. Duplicate `#s07-endcard` ID that hid Scene 7 Phase 1 (`79–85s`) → renamed inner overlay to `#s07-final-card`.
    2. 1-frame blank flashes at scene cuts (`11s`, `65s`, `79s`) → matched incoming entrance visibility at `t=0` and removed early fade-to-empty exits.
    3. Orphan character wrap (`閱`) on Scene 7 heading → tightened copy to `LINE 每日重點與 RSS 訂閱`.
- **Not checked**: Audio playback — this initial MP4 is rendered silent so you can drop your local **Minimax-Speech-2.8HD** cloned voice files (`vo-01.wav`..`vo-07.wav`) into `assets/audio/` and run `node scripts/attach-voiceover.mjs` to auto-normalize to `-16 LUFS` and re-render with voice.

## Weakest Shot & Future Polish
- **Weakest shot**: `s01-hook` (`0–6s`) uses recreated clinical browser panes (PubMed / Guideline PDF / NHI rules) rather than live recorded scrolling video; if you later capture a 6-second real browser scroll clip, it can drop straight into `#s01-panes`.
- **Next optional cut**: A 45-second 9:16 vertical edit for LINE physician groups using the 5 short voiceover slots in `guthub-demo-video-plan.md`.

## Warnings Kept on Purpose
- `font_face_local_only` (8 warnings on `GutHubTC` using `local("PingFang TC")`): intentional for local macOS rendering without bundling a 15 MB CJK font file into git; if moving to cloud render, swap in a `.woff2` Noto Sans TC subset.
- `film_silent` (1 warning): intentional until local Minimax-Speech-2.8HD WAV files (`vo-01.wav`..`vo-07.wav`) are attached via `scripts/attach-voiceover.mjs`.
