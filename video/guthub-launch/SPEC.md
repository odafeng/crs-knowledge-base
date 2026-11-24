# SPEC — GutHub (`guthub.tw`) Launch Film (Storyline A)

GOAL:    A Taiwanese colorectal surgeon finishes the 92-second film convinced that GutHub replaces scattered PubMed/guideline/NHI lookup with one verifiable, Taiwan-aligned evidence workstation — and visits guthub.tw or scans the LINE OA QR code.
OUTPUT:  HyperFrames, 1920 x 1080, 30 fps (2760 frames)
TIME:    92.0 s x 30 fps = 2760 frames; 7 voiceover-aligned scenes (vo-01..vo-07)

LOOK:    ground #f6f5f0 (warm archival paper) and #0f1f44 (colorectal awareness deep indigo masthead),
         dark mode #0f1217 with #161a22 cards and 1px #272d3a keylines;
         ink #111827 / #3a4252 on light, #ffffff / #cfd9f2 on indigo;
         one signal accent #8f2542 (editorial claret) reserved strictly for AI disclosure, freshness, and provenance check lines;
         regulatory status paired with icon+label only: #0b5d3c/#e6f4ec (approved/covered), #734604/#faf0d8 (conditional);
         display face Archivo (700/800, 44–112px, -0.02em) + PingFang TC (600/700, 30–68px),
         body/UI face Archivo + PingFang TC at 28–36px (no readable text below 28px);
         medium: real Taiwanese clinical-surgical journal & web workstation (1px hairlines, 4–10px editorial radii, crisp contact shadows).

OBJECTS: real GutHub brand disc (assets/brand/guthub-logo.png, 1254x1254), real LINE OA vector QR (assets/brand/line-oa-qr.svg, @742rxviu),
         large crisp pointer cursor (56px), 3 clinical browser panes (PubMed, Guideline PDF, NHI 9.134),
         real GutHub lead card (NICHE-2 Lancet 2026: 100% 3y DFS / 100% 5y OS / 111 cases / 58.7 mo),
         real AskSite bar ("左側 RAS 野生型一線用哪個標靶？" -> PARADIGM JAMA 2023 DOI 10.1001/jama.2023.4428 & FIRE-3),
         real Taiwan NHI board (9.134, 9.53 1., 9.27 1.(1), 9.69 1.(11)),
         real BRAF V600E Tumor Board A4 printable sheet (EC+mFOLFOX6 ORR 65.7% mPFS 12.8 mOS 30.3; BEACON HR 0.61),
         real verified surgeon forum thread (AZUR-1 dMMR rectal non-operative, 76% cCR/pCR, NHI 9.69),
         clinical mobile phone frame showing PWA offline badge & LINE OA daily push.

MOTION:  enter: expo.out / power4.out (14–22 frames); move/camera: power2.inOut (14–24 frames);
         exit: power3.in (8–12 frames); tactile click: linear press 3f -> back.out(1.6) 6f;
         stagger: list rows 2–3 frames (67–100 ms), total group <= 15 frames (0.5 s).

SHOTS:
  s01-hook        [0..330]     0.0–11.0s   07:20 Tumor Board 3-pane tension -> cursor click collapses into #0f1f44 Masthead + SVG KM motif + GutHub / guthub.tw
  s02-paperwatch  [330..780]   11.0–26.0s  Real NICHE-2 lead (100% DFS, 100% OS, 111 cases, 58.7 mo) -> camera push into SVG claret provenance line -> AI disclosure chips
  s03-asksite     [780..1200]  26.0–40.0s  AskSite bar morph -> stepped query typing -> cursor click -> "不產生答案" honesty badge -> PARADIGM (JAMA 2023, DOI) & FIRE-3
  s04-nhi-drugs   [1200..1590] 40.0–53.0s  Taiwan TFDA/NHI coverage board (4 real clauses) -> cursor clicks Encorafenib chip -> anchored drawer expands BRAF V600E evidence
  s05-tumorboard  [1590..1950] 53.0–65.0s  BRAF V600E Tumor Board one-pager -> cursor clicks Print -> A4 sheet lifts cleanly off archival desk with print header
  s06-forum-dark  [1950..2370] 65.0–79.0s  Verified surgeon forum (AZUR-1 thread + anonymous toggle) -> cursor clicks Dark Mode -> in-place theme crossfade + offline PWA phone
  s07-endcard     [2370..2760] 79.0–92.0s  Phone LINE OA daily digest notification + @742rxviu card -> indigo colour flood -> GutHub logo disc + guthub.tw + scannable QR + disclaimer

BANNED:  dark void with floating small UI; neon glow, bloom, lens flares, particles; purple/blue gradients; glass cards;
         3D-tilted product UI; docked corner logo; fade+slide-up on every element; text moving while being read;
         three generic feature cards in a row; invented trial numbers or fake buttons.

QA:      Check 0.2s (non-empty hook), 8.5s (masthead lock), 18.0s (provenance line), 34.0s (PARADIGM DOI),
         47.0s (NHI 9.134 drawer), 61.5s (A4 print sheet), 73.5s (dark mode + phone), 89.5s (end card + QR + disclaimer).
         Verify phone-width (360px) legibility across all 7 scenes and zero overlap/clipping findings in hyperframes check.
