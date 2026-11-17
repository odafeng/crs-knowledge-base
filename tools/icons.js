// App icons and favicons from the GutHub logo. Run after changing static/brand/guthub-logo.png: node tools/icons.js
// The logo is the two-colour colon above the GutHub wordmark on white. Small sizes use the colon only: the wordmark
// is unreadable at 16-64 px. The white background is unmixed into transparency, so the mark sits on any colour.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const LOGO = path.join(ROOT, 'static', 'brand', 'guthub-logo.png');
// Both sites serve the same icons: the current site (static/) and the Next.js site (apps/web/public/).
const SITES = [path.join(ROOT, 'static'), path.join(ROOT, 'apps', 'web', 'public')];
const WORDMARK_TOP = 0.68; // the colon ends above this fraction of the logo's height; the wordmark starts below it

// [file, size, how much of the canvas the colon fills, background]
const OUTPUTS = [
  ['favicon.png', 64, 0.8, 'tile'], // white rounded tile: the black half still shows on a dark tab bar
  ['icons/icon-192.png', 192, 0.8, 'white'],
  ['icons/icon-512.png', 512, 0.8, 'white'],
  ['icons/icon-maskable-512.png', 512, 0.6, 'white'], // inside the central 80% safe zone
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
    // Unmix white: alpha from the darkest channel, colour recovered from the blend with white.
    let [x0, y0, x1, y1] = [src.width, src.height, 0, 0];
    for (let i = 0; i < px.length; i += 4) {
      let a = 255 - Math.min(px[i], px[i + 1], px[i + 2]);
      a = a < 6 ? 0 : Math.min(255, Math.round((a * 255) / 249));
      if (a === 0) { px[i + 3] = 0; continue; }
      const f = a / 255;
      for (let c = 0; c < 3; c++) px[i + c] = Math.max(0, Math.min(255, Math.round((px[i + c] - (1 - f) * 255) / f)));
      px[i + 3] = a;
      if (a > 55) {
        const p = i / 4, x = p % src.width, y = Math.floor(p / src.width);
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      }
    }
    sctx.putImageData(data, 0, 0);
    const [w, h] = [x1 - x0 + 1, y1 - y0 + 1];
    const result = {};
    for (const [name, size, fill, bg] of outputs) {
      const canvas = new OffscreenCanvas(size, size);
      const ctx = canvas.getContext('2d');
      if (bg === 'white') { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, size, size); }
      if (bg === 'tile') { ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.roundRect(0, 0, size, size, size * 0.22); ctx.fill(); }
      const scale = (fill * size) / Math.max(w, h);
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
    return result;
  }, { logo, outputs: OUTPUTS, wordmarkTop: WORDMARK_TOP });
  for (const [name] of OUTPUTS)
    for (const site of SITES) fs.writeFileSync(path.join(site, name), Buffer.from(images[name], 'base64'));
  console.log(Object.keys(images).join('\n'));
  await browser.close();
})();
