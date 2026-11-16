const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');
const { chromium } = require('playwright');

const APP = path.resolve(__dirname, '../apps/web');
const NEXT = path.join(APP, 'node_modules/next/dist/bin/next');

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

for (const mode of ['start', 'dev']) {
  test(`Next.js ${mode}: startup, shared layout, navigation, and errors`, { timeout: 90000 }, async () => {
    const port = await freePort();
    const origin = `http://127.0.0.1:${port}`;
    const server = spawn(process.execPath, [NEXT, mode, '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: APP,
      env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    let browser;
    server.stdout.on('data', chunk => { output += chunk; });
    server.stderr.on('data', chunk => { output += chunk; });
    try {
      const deadline = Date.now() + 45000;
      let health;
      while (Date.now() < deadline && server.exitCode === null) {
        try {
          health = await fetch(`${origin}/api/health`, { signal: AbortSignal.timeout(5000) });
          if (health.ok) break;
        } catch { /* Wait for the real Next.js process to listen. */ }
        await delay(100);
      }
      assert.equal(health?.status, 200, output);
      assert.equal(health.headers.get('cache-control'), 'no-store');
      assert.deepEqual(await health.json(), { status: 'ok' });

      browser = await chromium.launch();
      const page = await browser.newPage({ viewport: { width: 360, height: 812 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const response = await page.goto(origin);
      assert.equal(response.status(), 200);
      assert.equal(await page.title(), 'GutHub｜大腸直腸外科實證更新');
      assert.equal(await page.locator('html').getAttribute('lang'), 'zh-Hant-TW');
      assert.equal(await page.locator('main h1').count(), 1);
      assert.match(await page.locator('main h1').innerText(), /實證與討論/);
      assert.equal(await page.getByRole('link', { name: '閱讀文獻', exact: true }).getAttribute('href'),
        'https://odafeng.github.io/crs-knowledge-base/updates/');
      assert.equal(await page.locator('meta[name="robots"]').getAttribute('content'), 'noindex, nofollow');
      for (const width of [360, 1280]) {
        await page.setViewportSize({ width, height: 812 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      }
      const font = await page.evaluate(async () => {
        await document.fonts.load('16px Archivo', 'GutHub');
        return document.fonts.check('16px Archivo', 'GutHub');
      });
      assert.equal(font, true);
      assert.equal((await page.request.get(`${origin}/favicon.svg`)).status(), 200);
      assert.equal((await page.goto(`${origin}/missing-page`)).status(), 404);
      await page.getByRole('link', { name: 'GutHub 首頁', exact: true }).click();
      await page.waitForURL(origin + '/');
      assert.match(await page.locator('main').innerText(), /實證與討論/);
      assert.deepEqual(errors, []);
    } finally {
      if (browser) await browser.close();
      const stopped = new Promise(resolve => server.once('exit', resolve));
      if (server.exitCode === null) {
        server.kill('SIGTERM');
        await stopped;
      }
    }
  });
}
