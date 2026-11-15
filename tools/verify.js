// Accessibility (axe-core), search and keyboard reach on a built site.
// Usage: node tools/verify.js [site dir] [comma-separated pages]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const { ORIGIN, BASE, PAGES: ALL_PAGES, serve } = require('./serve');

const SITE = path.resolve(process.argv[2] || path.join(__dirname, '..', 'site'));
const PAGES = process.argv[3] ? process.argv[3].split(',') : ALL_PAGES;
const axeSrc = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

(async () => {
  const b = await chromium.launch(); const problems = []; let runs = 0;
  for (const [width, scheme] of [[360, 'light'], [360, 'dark'], [375, 'light'], [1024, 'light'], [1280, 'light'], [1280, 'dark']]) {
    const ctx = await b.newContext({ serviceWorkers: 'block', viewport: { width, height: 812 }, colorScheme: scheme }); const p = await ctx.newPage(); await serve(p, SITE);
    const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
    for (const page of PAGES) {
      await p.goto(ORIGIN + BASE + page, { waitUntil: 'networkidle' });
      await p.addScriptTag({ content: axeSrc });
      const r = await p.evaluate(() => axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] } }));
      const overflow = await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
      runs++;
      if (r.violations.length || overflow) problems.push(`${page || 'home'} @${width} ${scheme}: ${r.violations.map(v => `${v.id}(${v.nodes.length}) ${v.nodes[0].target.join(' ')}`).join('; ')}${overflow ? ' H-OVERFLOW' : ''}`);
    }
    if (errs.length) problems.push(`console @${width} ${scheme}: ${[...new Set(errs)].join(' | ')}`);
    await ctx.close();
  }
  if (problems.length) process.exitCode = 1;
  console.log('axe runs:', runs, '| problems:', problems.length); problems.slice(0, 20).forEach(x => console.log('  -', x));
  const ctx = await b.newContext({ serviceWorkers: 'block', viewport: { width: 375, height: 812 } }); const p = await ctx.newPage(); await serve(p, SITE);
  await p.goto(ORIGIN + BASE, { waitUntil: 'networkidle' });
  const kb = await p.evaluate(() => ({ onclick: document.querySelectorAll('[onclick]').length, focusable: document.querySelectorAll('a[href],button,input').length, landmarks: ['header', 'nav', 'main', 'footer'].map(t => `${t}:${document.querySelectorAll(t).length}`).join(' '), h1: document.querySelectorAll('h1').length }));
  console.log('home semantics:', JSON.stringify(kb));
  await p.goto(ORIGIN + BASE + 'updates/', { waitUntil: 'networkidle' });
  await p.fill('#q', 'niche'); await p.waitForTimeout(500);
  console.log('first search result links to:', (await p.$eval('#search-results a', a => a.href)).replace(ORIGIN, ''));
  console.log('search "niche":', await p.$eval('#search-results', el => el.innerText.replace(/\n+/g, ' | ').slice(0, 220)));
  await p.fill('#q', 'dostarlimab rectal'); await p.waitForTimeout(300);
  console.log('search "dostarlimab rectal":', await p.$eval('#search-results', el => el.innerText.replace(/\n+/g, ' | ').slice(0, 200)));
  // Keyboard: every visible control on the home page must be reachable with Tab, at phone and desktop width.
  for (const width of [360, 1280]) {
    await p.setViewportSize({ width, height: 812 });
    await p.goto(ORIGIN + BASE, { waitUntil: 'networkidle' });
    const total = await p.evaluate(() => [...document.querySelectorAll('a[href], button, input, summary, [tabindex="0"]')].filter(e => !e.hidden && e.getClientRects().length).length);
    for (let i = 0; i < total + 5; i++) { await p.keyboard.press('Tab'); await p.evaluate(() => document.activeElement?.setAttribute('data-reached', '')); }
    const reached = await p.evaluate(() => document.querySelectorAll('[data-reached]:not(body)').length);
    console.log(`keyboard @${width}: Tab reaches ${reached} of ${total} controls on home`);
    if (reached < total) process.exitCode = 1;
  }
  await b.close();
})();
