#!/usr/bin/env node
/**
 * Attaches local Minimax-Speech-2.8HD WAV files (assets/audio/vo-01.wav .. vo-07.wav)
 * into index.html, normalizes them to -16 LUFS via ffmpeg, and prints the render command.
 *
 * Usage:
 *   node scripts/attach-voiceover.mjs [--bgm assets/audio/bgm.mp3]
 */
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const ROOT = path.resolve(import.meta.dirname, "..");
const SCRIPT_PATH = path.join(ROOT, "assets", "audio", "voiceover-script.json");
const INDEX_PATH = path.join(ROOT, "index.html");

const bgmFlagIdx = process.argv.indexOf("--bgm");
const bgmPath = bgmFlagIdx > -1 ? process.argv[bgmFlagIdx + 1] : null;

const spec = JSON.parse(fs.readFileSync(SCRIPT_PATH, "utf8"));
const normDir = path.join(ROOT, "assets", "audio", "normalized");
fs.mkdirSync(normDir, { recursive: true });

const tags = [];
const missing = [];

for (const seg of spec.segments) {
  const srcAbs = path.join(ROOT, seg.file);
  if (!fs.existsSync(srcAbs)) {
    missing.push(seg.file);
    continue;
  }
  const outName = `${seg.id}.norm.wav`;
  const outAbs = path.join(normDir, outName);
  execFileSync(
    "ffmpeg",
    [
      "-y",
      "-i",
      srcAbs,
      "-af",
      "loudnorm=I=-16:TP=-1.5:LRA=11",
      "-ar",
      "48000",
      "-ac",
      "1",
      outAbs,
    ],
    { stdio: "inherit" },
  );
  tags.push(
    `      <audio id="${seg.id}" class="clip" src="assets/audio/normalized/${outName}" data-start="${seg.startSec}" data-volume="1" data-track-index="2"></audio>`,
  );
}

if (bgmPath) {
  const bgmAbs = path.join(ROOT, bgmPath);
  if (!fs.existsSync(bgmAbs)) {
    console.error(`Missing BGM file: ${bgmPath}`);
    process.exit(1);
  }
  tags.push(
    `      <audio id="bgm-bed" class="clip" src="${bgmPath}" data-start="0" data-duration="${spec.totalDurationSec}" data-volume="0.14" data-fade-in="0.8" data-fade-out="2.0" data-track-index="3"></audio>`,
  );
}

if (missing.length > 0) {
  console.error("Missing voiceover files:\n" + missing.map((m) => `  - ${m}`).join("\n"));
  process.exit(1);
}

const html = fs.readFileSync(INDEX_PATH, "utf8");
const markerStart = "<!-- VOICEOVER_TRACKS_SLOT -->";
const block = `${markerStart}\n${tags.join("\n")}\n      <!-- END_VOICEOVER_TRACKS_SLOT -->`;
const updated = html.includes("<!-- END_VOICEOVER_TRACKS_SLOT -->")
  ? html.replace(/<!-- VOICEOVER_TRACKS_SLOT -->[\s\S]*?<!-- END_VOICEOVER_TRACKS_SLOT -->/, block)
  : html.replace(markerStart, block);

fs.writeFileSync(INDEX_PATH, updated, "utf8");
console.log(`Attached ${tags.length} audio clip(s) to index.html.`);
console.log("Next: render MP4 via hyperframes render -o out/guthub-launch-vo.mp4");
