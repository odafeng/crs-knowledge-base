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

// Reading pages (C2a #64) against a mock of the B5 read API: one item of every page type, all four figure kinds.
// Slugs differ from real content so a reused .next ISR cache cannot answer instead of the mock; CI builds fresh.
const http = require('node:http');

const topic = {
  key: 'mCRC-BRAF-V600E', slug: 'smoke-braf', label: 'BRAF V600E', title: 'BRAF V600E 突變型 mCRC', paperCount: 1,
  standardOfCare: [{
    title: '第二線以上治療', icon: '', reviewedAt: '2026-11-16', refs: [],
    body_html: '<p>見 <a href="docs/beacon.html">BEACON 整理</a></p><table><tr><th></th><th>方案</th></tr></table>',
    regulatory: [{ regimen: 'Encorafenib + cetuximab', fda: 'approved', tfda: 'approved', nhi: 'conditional',
      nhiNote: '給付規定 9.134', checkedAt: '2026-11-16' }],
  }],
  roboticSections: [],
};
const robotic = {
  key: 'robotic-surgery', slug: 'robotic', label: '機器手臂手術', title: '機器手臂手術', paperCount: 0, standardOfCare: [],
  roboticSections: [{ slug: 'tme', timeline: [{ yr: 2017, venue: 'JAMA', finding: 'ROLARR<br>轉換率 NS' }],
    cards: [{ title: 'TME 品質', tag: 'RCT', body: '<p>REAL 試驗</p>' }], detailHtml: ['<h3>詳細</h3><p>內容</p>'] }],
};
const paper = {
  id: 'BEACON_2019', slug: 'smoke-beacon', topic: topic.key, year: 2019, journal: 'NEJM', studyType: 'Phase 3 RCT',
  n: 665, regimen: 'Encorafenib + cetuximab', endpoint: 'OS', result: 'mOS 9.0 vs 5.4 個月', bottomLine: '二線標準治療',
  doi: '10.1056/x', relations: [], source: 'fulltext', reviewedAt: '2026-06-07', review: { status: 'auto', publishedAt: '2026-06-07' },
  commentary: [{ doi: '10.1056/c', title: '社論標題', journal: 'NEJM', year: 2019, type: 'Editorial', summary: '評論摘要',
    critique: false, newData: false, addedAt: '2026-06-07' }],
  detailHtml: '<h3>試驗設計</h3><p>隨機分配</p>',
};
const story = {
  id: 'smoke-news', paperId: paper.id, publishedAt: '2026-11-01', headline: ['BEACON：', '二線存活延長'], dek: '摘要',
  key: { label: 'mOS', value: '9.0', unit: '個月' }, review: { status: 'auto' }, figureNote: '數字出處：NEJM',
  body: [{ heading: '發生了什麼', text: '內文' }],
  figures: [
    { kind: 'numbers', stats: [{ label: 'ORR', value: '26', unit: '%' }] },
    { kind: 'compare', armA: 'EC', armB: '對照', rows: [{ label: 'mOS', unit: '個月', a: 9.0, b: 5.4 }] },
    { kind: 'meters', rows: [{ label: '反應率', percent: 26 }] },
    { kind: 'interval', label: 'HR', point: 0.52, low: 0.39, high: 0.7 },
  ],
};

function mockApi() {
  const page = items => ({ items, nextCursor: null });
  const notFound = { error: { code: 'not_found', message: 'Not found', requestId: 'mock' } };
  return http.createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://mock');
    const routes = {
      '/api/v1/papers': page([paper]),
      '/api/v1/news': page([story]),
      '/api/v1/topics': page([topic, robotic]),
      [`/api/v1/news/${story.id}`]: story,
    };
    const body = routes[pathname];
    res.writeHead(body ? 200 : 404, { 'content-type': 'application/json' });
    res.end(JSON.stringify(body ?? notFound));
  });
}

let api;
test.before(async () => {
  api = mockApi();
  await new Promise(resolve => api.listen(0, '127.0.0.1', resolve));
});
test.after(() => new Promise(resolve => api.close(resolve)));
const apiUrl = () => `http://127.0.0.1:${api.address().port}/api/v1`;

for (const mode of ['start', 'dev']) {
  test(`Next.js ${mode}: startup, shared layout, navigation, and errors`, { timeout: 90000 }, async () => {
    const port = await freePort();
    const origin = `http://127.0.0.1:${port}`;
    const server = spawn(process.execPath, [NEXT, mode, '--hostname', '127.0.0.1', '--port', String(port)], {
      cwd: APP,
      env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1', GUTHUB_API_URL: apiUrl() },
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
      assert.equal(await page.locator('main h1').textContent(), 'GutHub：大腸直腸外科實證更新');
      assert.equal(await page.getByRole('link', { name: '讀這則消息' }).getAttribute('href'), '/news/smoke-news/');
      assert.equal(await page.locator('.tabbar a[aria-current="page"]').innerText(), '首頁');
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
      // Brand (C4 #66): installable with the GutHub name, and every icon or share image it names is served.
      const manifestHref = await page.locator('link[rel="manifest"]').getAttribute('href');
      const manifestUrl = new URL(manifestHref, origin);
      const manifest = await (await page.request.get(manifestUrl.href)).json();
      assert.equal(manifest.short_name, 'GutHub');
      const assets = [
        ...manifest.icons.map(icon => new URL(icon.src, manifestUrl).href),
        new URL(await page.locator('link[rel="apple-touch-icon"]').getAttribute('href'), origin).href,
      ];
      for (const asset of assets) assert.equal((await page.request.get(asset)).status(), 200, asset);
      assert.equal((await page.goto(`${origin}/missing-page`)).status(), 404);
      await page.getByRole('link', { name: /^GutHub/ }).click();
      await page.waitForURL(origin + '/');
      assert.match(await page.locator('main').innerText(), /新收錄文獻/);
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

test('Next.js start: reading pages render from the read API', { timeout: 90000 }, async () => {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.execPath, [NEXT, 'start', '--hostname', '127.0.0.1', '--port', String(port)], {
    cwd: APP,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: '1', GUTHUB_API_URL: apiUrl() },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '';
  let browser;
  server.stdout.on('data', chunk => { output += chunk; });
  server.stderr.on('data', chunk => { output += chunk; });
  try {
    const deadline = Date.now() + 45000;
    while (Date.now() < deadline && server.exitCode === null) {
      try { if ((await fetch(`${origin}/api/health`)).ok) break; } catch { /* not listening yet */ }
      await delay(100);
    }
    const expectations = {
      '/papers/smoke-beacon/': ['關鍵結果', '試驗設計', '社論', 'https://doi.org/10.1056/x', 'AI 依摘要整理', '收案數'],
      '/news/smoke-news/': ['二線存活延長', 'class="figure"', 'class="compare"', 'class="meters"', 'interval__point', '看文獻整理'],
      '/mcrc/smoke-braf/': ['核准與給付現況', '有條件給付', '給付規定 9.134', 'BEACON 整理', '二線標準治療'],
      '/robotic/tme/': ['機器手臂 TME', 'ROLARR，轉換率 NS', 'TME 品質', '詳細'],
      '/': ['二線存活延長', '本週新增', '新收錄文獻', '社論標題', '核准與給付現況', 'FDA 已核准', '機器手臂 TME'],
      '/topics/': ['mCRC 治療', '機器手臂手術', '最新：Encorafenib + cetuximab'],
      '/mcrc/': ['BRAF V600E', '1</span>篇文獻'],
      '/robotic/': ['機器手臂 TME', '證據演進有 1 個時間點'],
      '/updates/': ['共 2 則', '評論', '社論標題'],
      '/news/': ['二線存活延長', 'AI 新聞稿', 'RSS'],
      '/about/': ['內容怎麼產生', 'AI 新聞稿'],
      '/subscribe/': ['/rss.xml', '/feed/news.xml', '/feed/smoke-braf.xml', '/atom.xml', '/feed.json'],
    };
    for (const [path, needles] of Object.entries(expectations)) {
      const response = await fetch(origin + path);
      assert.equal(response.status, 200, `${path}\n${output}`);
      // React separates adjacent text nodes with <!-- --> in server HTML; compare the visible text run.
      const html = (await response.text()).replaceAll('<!-- -->', '');
      for (const needle of needles) assert.ok(html.includes(needle), `${path} lacks ${needle}`);
      assert.ok(!html.includes('href="docs/'), `${path} keeps a link into docs/`);
    }
    // Feeds keep the current site's IDs and are served without a trailing-slash redirect (C2c #92).
    const feedChecks = {
      '/rss.xml': ['<guid isPermaLink="false">tag:odafeng.github.io,2026:paper/smoke-beacon</guid>',
        '<link>https://odafeng.github.io/crs-knowledge-base/news/smoke-news/</link>'],
      '/feed/news.xml': ['tag:odafeng.github.io,2026:news/smoke-news'],
      '/feed/smoke-braf.xml': ['tag:odafeng.github.io,2026:commentary/smoke-beacon/10.1056/c'],
      '/atom.xml': ['<id>tag:odafeng.github.io,2026:feed/atom.xml</id>'],
      '/feed.json': ['"id": "tag:odafeng.github.io,2026:news/smoke-news"'],
      '/sitemap.xml': ['<loc>https://odafeng.github.io/crs-knowledge-base/robotic/tme/</loc>'],
      '/robots.txt': ['Sitemap: https://odafeng.github.io/crs-knowledge-base/sitemap.xml'],
    };
    for (const [path, needles] of Object.entries(feedChecks)) {
      const response = await fetch(origin + path, { redirect: 'manual' });
      assert.equal(response.status, 200, path);
      const body = await response.text();
      for (const needle of needles) assert.ok(body.includes(needle), `${path} lacks ${needle}`);
    }
    // AI-unreviewed pages stay out of the sitemap, like the current site.
    assert.ok(!(await (await fetch(`${origin}/sitemap.xml`)).text()).includes('/papers/smoke-beacon/'));
    const paperHtml = await (await fetch(`${origin}/papers/smoke-beacon/`)).text();
    assert.ok(paperHtml.includes('<link rel="canonical" href="https://odafeng.github.io/crs-knowledge-base/papers/smoke-beacon/"/>'));
    assert.ok(paperHtml.includes('"@type":"MedicalWebPage"'));
    for (const path of ['/papers/BEACON_2019/', '/papers/beacon-2019/', '/news/missing/', '/mcrc/robotic/', '/robotic/nope/']) {
      assert.equal((await fetch(origin + path)).status, 404, path);
    }

    browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 360, height: 812 } });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`${origin}/news/smoke-news/`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByRole('link', { name: '看文獻整理' }).click();
    await page.waitForURL(`${origin}/papers/smoke-beacon/`);
    assert.equal(await page.locator('main h1').innerText(), 'Encorafenib + cetuximab');
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
