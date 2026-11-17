// App icons and favicons from the GutHub logo. Run after changing static/brand/guthub-logo.png: node tools/icons.js
// The logo is an orange colon above the GutHub wordmark, on a deep navy disc. Small sizes use the colon only: the
// wordmark is unreadable at 16-64 px. The colon is lifted off the navy (alpha from how far each pixel has moved from
// navy toward the colon's orange) and redrawn centred on a fresh navy disc or square.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const LOGO = path.join(ROOT, 'static', 'brand', 'guthub-logo.png');
// Both sites serve the same icons: the current site (static/) and the Next.js site (apps/web/public/).
const SITES = [path.join(ROOT, 'static'), path.join(ROOT, 'apps', 'web', 'public')];
const WORDMARK_TOP = 0.612; // the colon ends above this fraction of the logo's height; the wordmark starts below it

// [file, size, how much of the canvas the colon fills, background]
const OUTPUTS = [
  ['favicon.png', 64, 0.62, 'disc'], // navy disc: reads on light and dark tab bars alike
  ['icons/icon-192.png', 192, 0.62, 'square'], // full-bleed; iOS and Android round the corners themselves
  ['icons/icon-512.png', 512, 0.62, 'square'],
  ['icons/icon-maskable-512.png', 512, 0.5, 'square'], // inside the central 80% safe zone
  ['icons/badge-96.png', 96, 0.9, 'badge'], // Android draws only the alpha channel: white on transparent
];

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const logo = `data:image/png;base64,${fs.readFileSync(LOGO).toString('base64')}`;
  const images = await page.evaluate(async ({ logo, outputs, wordmarkTop }) => {
    const img = new Image();
    img.src = logo;
    await img.decode();
    const src = new OffscreenCanvas(img.width, Math.round(img.height * wordmarkTop));
    const sctx = src.getContext('2d');
    sctx.drawImage(img, 0, 0);
    const data = sctx.getImageData(0, 0, src.width, src.height);
    const px = data.data;
    const at = (x, y) => Array.from(px.slice((y * src.width + x) * 4, (y * src.width + x) * 4 + 3));
    const navy = at(Math.round(src.width * 0.16), Math.round(src.height * 0.9)); // inside the disc, left of the colon
    // The colon's orange: the brightest-red pixel in the crop.
    let orange = navy;
    for (let i = 0; i < px.length; i += 4) if (px[i] - px[i + 2] > orange[0] - orange[2]) orange = [px[i], px[i + 1], px[i + 2]];
    const d = orange.map((c, k) => c - navy[k]);
    const len2 = d.reduce((s, v) => s + v * v, 0);
    let [x0, y0, x1, y1] = [src.width, src.height, 0, 0];
    for (let i = 0; i < px.length; i += 4) {
      const v = [px[i] - navy[0], px[i + 1] - navy[1], px[i + 2] - navy[2]];
      const t = Math.max(0, Math.min(1, (v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) / len2));
      const off = Math.hypot(v[0] - t * d[0], v[1] - t * d[1], v[2] - t * d[2]); // far off the navy-orange line: the white corners
      const a = off > 60 || t < 0.04 ? 0 : Math.round(t * 255);
      [px[i], px[i + 1], px[i + 2], px[i + 3]] = [...orange, a];
      if (a > 128) {
        const p = i / 4, x = p % src.width, y = Math.floor(p / src.width);
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      }
    }
    sctx.putImageData(data, 0, 0);
    const [w, h] = [x1 - x0 + 1, y1 - y0 + 1];
    const fill = `rgb(${navy.join(' ')})`;
    const result = {};
    for (const [name, size, part, bg] of outputs) {
      const canvas = new OffscreenCanvas(size, size);
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = fill;
      if (bg === 'square') ctx.fillRect(0, 0, size, size);
      if (bg === 'disc') { ctx.beginPath(); ctx.arc(size / 2, size / 2, size / 2, 0, 2 * Math.PI); ctx.fill(); }
      const scale = (part * size) / Math.max(w, h);
      const [dw, dh] = [w * scale, h * scale];
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(src, x0, y0, w, h, (size - dw) / 2, (size - dh) / 2, dw, dh);
      if (bg === 'badge') { ctx.globalCompositeOperation = 'source-in'; ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, size, size); }
      const blob = await canvas.convertToBlob({ type: 'image/png' });
      result[name] = await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.readAsDataURL(blob);
      });
    }
    return { result, navy, orange };
  }, { logo, outputs: OUTPUTS, wordmarkTop: WORDMARK_TOP });
  for (const [name] of OUTPUTS)
    for (const site of SITES) fs.writeFileSync(path.join(site, name), Buffer.from(images.result[name], 'base64'));
  console.log('navy', images.navy, 'orange', images.orange);
  await browser.close();
})();
