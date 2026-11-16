// Accessibility (axe-core), layout and the main reading flow on the running Next.js site (C2d #93).
// Usage: node tools/next-verify.js <Next.js origin>
// Same axe tags and representative pages as verify.js uses for the current site.
const { chromium } = require('playwright');
const fs = require('fs');
const { PAGES } = require('./serve');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
// Pages only the Next.js site has (D1 #67), checked as a visitor sees them.
const NEXT_ONLY = ['login/', 'account/', 'auth/callback/', 'admin/comments/', 'tumor-board/', 'tumor-board/ras-wt/', 'privacy/'];
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  let runs = 0;
  for (const [width, scheme] of [[360, 'light'], [360, 'dark'], [1280, 'light'], [1280, 'dark']]) {
    const context = await browser.newContext({ viewport: { width, height: 812 }, colorScheme: scheme });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    for (const path of [...PAGES, ...NEXT_ONLY]) {
      const response = await page.goto(`${ORIGIN}/${path}`, { waitUntil: 'load' });
      if (response.status() !== 200) problems.push(`/${path} @${width}: HTTP ${response.status()}`);
      await page.addScriptTag({ content: axeSrc });
      const result = await page.evaluate(tags => axe.run(document, { runOnly: { type: 'tag', values: tags } }), TAGS);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      runs++;
      if (result.violations.length || overflow) {
        problems.push(`/${path} @${width} ${scheme}: ${result.violations.map(v => `${v.id}(${v.nodes.length}) ${v.nodes[0].target.join(' ')}`).join('; ')}${overflow ? ' H-OVERFLOW' : ''}`);
      }
    }
    if (errors.length) problems.push(`page errors @${width} ${scheme}: ${[...new Set(errors)].join(' | ')}`);
    await context.close();
  }
  // Tumor board sheets (G7 #118) must print on one A4 page.
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${ORIGIN}/tumor-board/`);
    const boards = await page.locator('.tile a').evaluateAll(links => links.map(a => a.getAttribute('href')));
    if (boards.length === 0) problems.push('tumor board: no topic sheets listed');
    for (const href of boards) {
      await page.goto(`${ORIGIN}${href}`, { waitUntil: 'networkidle' });
      const pdf = (await page.pdf({ format: 'A4' })).toString('latin1');
      const pages = (pdf.match(/\/Type\s*\/Page[^s]/g) || []).length;
      if (pages !== 1) problems.push(`tumor board ${href}: prints on ${pages} A4 pages`);
    }
    console.log('tumor board:', boards.length, 'sheets checked for one A4 page');
    await context.close();
  }
  console.log('axe runs:', runs, '| problems:', problems.length);
  problems.slice(0, 200).forEach(problem => console.log('  -', problem));

  // The main reading flow, by mouse and by keyboard: home -> story -> paper -> topic.
  const context = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await context.newPage();
  await page.goto(`${ORIGIN}/`);
  await page.locator('.lead__headline a').click();
  await page.waitForURL(/\/news\/[^/]+\/$/);
  await page.getByRole('link', { name: '看文獻整理' }).click();
  await page.waitForURL(/\/papers\/[^/]+\/$/);
  const paperTitle = await page.locator('main h1').innerText();
  await page.locator('.breadcrumb a').last().click();
  await page.waitForURL(/\/mcrc\/[^/]+\/$/);
  console.log('flow: home -> story -> paper', JSON.stringify(paperTitle.slice(0, 40)), '-> topic', new URL(page.url()).pathname);

  // Today's one thing (G4 #115): above the lead, labelled with its freshness, and its link opens a page.
  await page.goto(`${ORIGIN}/`);
  const daily = page.locator('section.daily');
  if (await daily.count() !== 1) problems.push('home: no daily pick shown');
  else {
    const label = await daily.locator('h2').innerText();
    if (!/^(今天的一件事|最近的一件事・\d+ 月 \d+ 日)$/.test(label)) problems.push(`home: daily label ${label}`);
    const before = await page.evaluate(() => {
      const [d, lead] = [document.querySelector('section.daily'), document.querySelector('section.lead')];
      return Boolean(d && lead && d.compareDocumentPosition(lead) & Node.DOCUMENT_POSITION_FOLLOWING);
    });
    if (!before) problems.push('home: daily pick is not above the lead story');
    await daily.locator('a').first().click();
    await page.waitForURL(/\/(news|papers)\/[^/]+\/$/);
    console.log('daily:', label, '->', new URL(page.url()).pathname);
  }

  await page.goto(`${ORIGIN}/`);
  const reached = new Set();
  for (let i = 0; i < 80; i++) {
    await page.keyboard.press('Tab');
    const href = await page.evaluate(() => document.activeElement?.getAttribute('href'));
    if (href) reached.add(href);
  }
  const visible = await page.evaluate(() =>
    [...document.querySelectorAll('a[href]')]
      .filter(a => a.offsetParent !== null && getComputedStyle(a).visibility !== 'hidden')
      .map(a => a.getAttribute('href')));
  const unreachable = [...new Set(visible)].filter(href => !reached.has(href));
  console.log('keyboard: reached', reached.size, 'links; visible but not reached in 80 Tabs:', unreachable.length ? unreachable.slice(0, 5) : 'none');
  await browser.close();
  if (problems.length) process.exitCode = 1;
})();
