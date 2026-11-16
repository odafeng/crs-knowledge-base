// App icons from the logo mark. Run once after changing the mark: node tools/icons.js
const { chromium } = require('playwright');
const path = require('path');
// Both sites serve the same icons: the current site (static/) and the Next.js site (apps/web/public/).
const OUTS = [path.join(__dirname, '..', 'static', 'icons'), path.join(__dirname, '..', 'apps', 'web', 'public', 'icons')];
const curves = (faint, solid, dot) => `<path d="M7 9h3v9h7v5h8" fill="none" stroke="${faint}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><path d="M7 9h6v6h6v5h5" fill="none" stroke="${solid}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="25" cy="20" r="2.75" fill="${dot}"/>`;
const mark = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#1B3BC4"/>${curves('rgb(255 255 255 / .45)', '#fff', '#FF8FB1')}</svg>`;
// Maskable: full-bleed field, the mark inside the central 80% safe zone.
const maskable = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="#1B3BC4"/><g transform="translate(5.6 5.6) scale(.65)">${curves('rgb(255 255 255 / .45)', '#fff', '#FF8FB1')}</g></svg>`;
// Badge: Android draws only the alpha channel, so the shape is white on transparent.
const badge = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">${curves('rgb(255 255 255 / .5)', '#fff', '#fff')}</svg>`;
(async () => {
  const browser = await chromium.launch();
  for (const [name, svg, size] of [['icon-192.png', mark, 192], ['icon-512.png', mark, 512], ['icon-maskable-512.png', maskable, 512], ['badge-96.png', badge, 96]]) {
    const page = await browser.newPage({ viewport: { width: size, height: size } });
    await page.setContent(`<body style="margin:0;background:transparent">${svg.replace('<svg ', `<svg width="${size}" height="${size}" style="display:block" `)}</body>`);
    for (const out of OUTS) await page.screenshot({ path: path.join(out, name), omitBackground: true });
    await page.close();
    console.log(name);
  }
  await browser.close();
})();
