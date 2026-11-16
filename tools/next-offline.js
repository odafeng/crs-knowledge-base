// Search, reading preferences and offline reading on the running Next.js site (C3 #65).
// Usage: node tools/next-offline.js <Next.js origin>
const { chromium } = require('playwright');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
const CACHE = 'guthub-public-v1';
const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };

const cachedPaths = page => page.evaluate(async name =>
  (await (await caches.open(name)).keys()).map(r => new URL(r.url).pathname), CACHE);

(async () => {
  const browser = await chromium.launch();

  // Search states, with the service worker out of the way so the network can fail.
  {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const page = await context.newPage();
    await page.goto(`${ORIGIN}/updates/#q`);
    const input = page.locator('#q');
    const results = page.locator('#search-results');
    check(await input.evaluate(el => el === document.activeElement), 'search: #q does not focus the box');
    await input.fill('n');
    check((await results.innerText()) === '', 'search: one character should not search');
    await input.fill('zzzzqq');
    await results.getByText('找不到符合的消息或文獻').waitFor();
    await input.fill('niche');
    await results.getByText(/找到 \d+ 筆/).waitFor();
    const first = results.locator('a').first();
    const href = await first.getAttribute('href');
    await first.click();
    await page.waitForURL(`${ORIGIN}${href}`);
    check((await page.locator('main h1').count()) === 1, `search: ${href} has no heading`);

    const offline = await context.newPage();
    await offline.route('**/search.json', route => route.abort('internetdisconnected'));
    await offline.goto(`${ORIGIN}/updates/`);
    await offline.locator('#q').fill('niche');
    await offline.locator('#search-results').getByText('無法載入搜尋資料').waitFor();
    console.log('search: focus, short query, no results, results -> page, network error ok');
    await context.close();
  }

  // Preferences persist and large text does not widen the page on a phone.
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 800 }, serviceWorkers: 'block' });
    const page = await context.newPage();
    await page.goto(`${ORIGIN}/`);
    await page.getByRole('button', { name: '特大字級' }).click();
    await page.getByRole('button', { name: '深色模式' }).click();
    const theme = await page.evaluate(() => document.documentElement.dataset.theme);
    await page.goto(`${ORIGIN}/papers/niche2/`);
    const after = await page.evaluate(() => ({ ...document.documentElement.dataset }));
    check(after.fontSize === 'xl' && after.theme === theme, `prefs: not kept across pages ${JSON.stringify(after)}`);
    check(await page.getByRole('button', { name: '特大字級' }).getAttribute('aria-pressed') === 'true', 'prefs: xl button not pressed');
    for (const path of ['/papers/niche2/', '/mcrc/msi-h/', '/updates/']) {
      await page.goto(`${ORIGIN}${path}`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      check(!overflow, `prefs: ${path} overflows at 360px with xl text`);
    }
    console.log('prefs: theme', theme, '+ xl text kept across pages; no overflow at 360px');
    await context.close();
  }

  // Offline reading: after one visit, unvisited public pages and search work without a network.
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${ORIGIN}/`);
    await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready;
      registration.active.postMessage({ type: 'sync', force: true });
    });
    let paths = [];
    for (let i = 0; i < 120 && !paths.includes('/papers/niche2/'); i++) {
      await page.waitForTimeout(500);
      paths = await cachedPaths(page);
    }
    for (let i = 0, last = -1; i < 60 && paths.length !== last; i++) {
      last = paths.length;
      await page.waitForTimeout(1000);
      paths = await cachedPaths(page);
    }
    const pages = paths.filter(p => /^\/(papers|news)\//.test(p));
    console.log('offline: cached', paths.length, 'entries,', pages.length, 'papers/news pages');
    const leaked = paths.filter(p => /^\/(api|auth|me|account|admin)(\/|$)/.test(p) || p.includes('_rsc'));
    check(leaked.length === 0, `offline: private or RSC entries cached: ${leaked.join(', ')}`);
    for (const shell of ['/', '/updates/', '/news/', '/topics/', '/search.json']) {
      check(paths.includes(shell), `offline: ${shell} not cached`);
    }

    await context.setOffline(true);
    const target = pages.find(p => p.startsWith('/papers/') && p !== '/papers/niche2/') || '/papers/niche2/';
    const response = await page.goto(`${ORIGIN}${target}`);
    check(response && response.ok(), `offline: ${target} did not open`);
    const styled = await page.evaluate(() => getComputedStyle(document.querySelector('.site-header')).position);
    check(styled === 'sticky', `offline: ${target} lost its stylesheet (header position ${styled})`);

    await page.goto(`${ORIGIN}/updates/`);
    await page.locator('#q').fill('niche');
    await page.locator('#search-results').getByText(/找到 \d+ 筆/).waitFor();
    await page.locator('#search-results a').first().click();
    await page.waitForURL(/\/(papers|news)\/[^/]+\/$/);
    check((await page.locator('main h1').count()) === 1, 'offline: search result did not open');
    console.log('offline:', target, 'opened styled; search and result link work offline');
    await context.close();
  }

  await browser.close();
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
