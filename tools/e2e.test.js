// Real HTTP and a real Service Worker: exercise the same base path used by GitHub Pages.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const SITE = path.resolve(process.env.SITE_DIR || path.join(__dirname, '..', 'site'));
const BASE = '/crs-knowledge-base/';
const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.xml': 'application/xml', '.png': 'image/png',
  '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.webmanifest': 'application/manifest+json',
};

test('new site: navigation, news, search, preferences, and offline reading', async () => {
  const server = http.createServer((req, res) => {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (!pathname.startsWith(BASE)) return res.writeHead(404).end();
    let file = path.join(SITE, pathname.slice(BASE.length));
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
    if (!fs.existsSync(file)) return res.writeHead(404).end();
    res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'text/plain' });
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch();
  try {
    const context = await browser.newContext({ viewport: { width: 360, height: 812 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin + BASE);
    await page.evaluate(() => navigator.serviceWorker.ready);
    assert.match(await page.locator('main').innerText(), /頭條/);
    assert.equal(await page.locator('h1').count(), 1);
    assert.equal(await page.locator('header [data-push-toggle]').isVisible(), false);
    await page.locator('.lead__actions a').click();
    await page.waitForURL('**/news/niche2-five-year/');
    assert.equal(await page.locator('meta[name="robots"]').getAttribute('content'), 'noindex, follow');
    assert.match(await page.locator('main').innerText(), /尚未經人工審核/);
    await page.goto(origin + BASE + 'updates/');
    await page.locator('#q').fill('niche');
    await page.locator('#search-results a').first().waitFor();
    await page.locator('#search-results a').first().click();
    assert.match(page.url(), /\/(papers|news)\//);
    await page.goto(origin + BASE + 'papers/niche2-os/');
    assert.match(await page.locator('#detail + .richtext').innerText(), /58.7 個月/);
    await page.locator('.display-settings [data-action="toggle-theme"]').click();
    await page.locator('[data-font-size-option="lg"]').click();
    await page.reload();
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    assert.equal(await page.locator('html').getAttribute('data-font-size'), 'lg');
    for (const width of [360, 1280]) {
      await page.setViewportSize({ width, height: 812 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }
    await context.setOffline(true);
    await page.goto(origin + BASE + 'mcrc/her2/');
    assert.match(await page.locator('h1').innerText(), /HER2/);
    await page.goto(origin + BASE + 'updates/');
    await page.locator('#q').fill('niche');
    await page.locator('#search-results a').first().waitFor();
    await context.setOffline(false);
    const old = await page.goto(origin + BASE + 'docs/mCRC-BRAF-V600E/Kopetz_NEJM_2019_BEACON.html');
    assert.equal(old.status(), 404);
    assert.equal(errors.length, 0, errors.join('\n'));
    await context.close();
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
});
