// Screenshots for documentation. Chinese text is drawn with Noto Sans TC, loaded only for the picture:
// build machines rarely have PingFang TC or Microsoft JhengHei, which readers' devices use.
// Usage: node tools/shots.js <out dir> [site dir]   (needs @fontsource-variable/noto-sans-tc)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { ORIGIN, BASE, serve } = require('./serve');

const OUT = path.resolve(process.argv[2]);
const SITE = path.resolve(process.argv[3] || path.join(__dirname, '..', 'site'));
const NOTO = path.dirname(require.resolve('@fontsource-variable/noto-sans-tc/package.json'));
const MOUNTS = { '/__noto/': NOTO, '/__out/': OUT };
const PHONE = { width: 360, height: 780 };  // Galaxy S24
const PHONES = [['', 'light', 'm-home.png'], ['news/ifebemtinib-garsorasib/', 'light', 'm-story.png'], ['mcrc/msi-h/', 'dark', 'm-topic.png']];
const DESKTOP = [['', 'light', 'home-desktop.png', 1480], ['news/breakwater-os/', 'light', 'story-desktop.png', 1180],
  ['news/', 'light', 'news-desktop.png', 1000], ['mcrc/msi-h/', 'dark', 'topic-desktop-dark.png', 1100]];

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const shot = async (rel, viewport, scheme, name) => {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2, colorScheme: scheme });
    const page = await ctx.newPage();
    await serve(page, SITE, MOUNTS);
    await page.goto(ORIGIN + BASE + rel, { waitUntil: 'networkidle' });
    await page.addStyleTag({ url: ORIGIN + '/__noto/index.css' });
    await page.addStyleTag({ content: ":root{--font-sans:'Archivo','Noto Sans TC Variable',sans-serif}" });
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(OUT, name) });
    await ctx.close();
  };
  for (const [rel, scheme, name, height] of DESKTOP) await shot(rel, { width: 1280, height }, scheme, name);
  for (const [rel, scheme, name] of PHONES) await shot(rel, PHONE, scheme, name);

  // Three phone screens side by side in one picture.
  const ctx = await browser.newContext({ viewport: { width: 1300, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await serve(page, SITE, MOUNTS);
  await page.goto(ORIGIN + BASE + 'about/');
  const figures = PHONES.map(([, , file]) => `<img src="${ORIGIN}/__out/${file}" width="${PHONE.width}" height="${PHONE.height}" style="display:block;border-radius:22px;box-shadow:0 8px 24px rgb(11 20 51 / .2)">`);
  await page.setContent(`<body style="margin:0;padding:32px;background:#E3E7F1;display:flex;gap:28px;width:max-content">${figures.join('')}</body>`);
  await page.waitForLoadState('networkidle');
  const box = await page.evaluate(() => { const r = document.body.getBoundingClientRect(); return { width: Math.ceil(r.width), height: Math.ceil(r.height) }; });
  await page.screenshot({ path: path.join(OUT, 'mobile-three.png'), clip: { x: 0, y: 0, ...box } });
  await browser.close();
  for (const [, , file] of PHONES) fs.unlinkSync(path.join(OUT, file));
  for (const file of fs.readdirSync(OUT)) console.log(file, Math.round(fs.statSync(path.join(OUT, file)).size / 1024), 'KB');
})();
