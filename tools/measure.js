// Line-length check: no wrapped block of running text may exceed LIMIT full-width characters per line.
// A line's length is its rendered width divided by the block's font size, so the limit holds at every text size.
// Usage: node tools/measure.js [site dir]
const { chromium } = require('playwright');
const path = require('path');
const { ORIGIN, BASE, PAGES, serve } = require('./serve');

const SITE = path.resolve(process.argv[2] || path.join(__dirname, '..', 'site'));
const WIDTHS = [1024, 1280, 1440];
const LIMIT = 40;

// Runs in the page. Table cells are reported separately: they hold data, and a table sets its own column widths.
function longestLines() {
  const blocks = document.querySelectorAll('main p, main li, main dd, main summary, main td, footer p');
  const found = [];
  for (const el of blocks) {
    if (el.querySelector('p, li, dd, td')) continue;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const lines = new Map();
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const range = document.createRange();
      range.selectNodeContents(node);
      for (const r of range.getClientRects()) {
        if (!r.width) continue;
        const top = Math.round(r.top / 4);
        const line = lines.get(top) || { left: r.left, right: r.right };
        lines.set(top, { left: Math.min(line.left, r.left), right: Math.max(line.right, r.right) });
      }
    }
    if (lines.size < 2) continue;
    const width = Math.max(...[...lines.values()].map(l => l.right - l.left));
    const size = parseFloat(getComputedStyle(el).fontSize);
    found.push({ chars: width / size, inTable: !!el.closest('table'), text: el.innerText.trim().slice(0, 28) });
  }
  return found;
}

(async () => {
  const browser = await chromium.launch();
  let worst = 0, worstCell = 0, blocks = 0;
  const over = [];
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 } });
    const page = await ctx.newPage();
    await serve(page, SITE);
    for (const rel of PAGES) {
      await page.goto(ORIGIN + BASE + rel, { waitUntil: 'networkidle' });
      await page.evaluate(() => { document.querySelectorAll('details').forEach(d => { d.open = true; }); return document.fonts.ready; });
      for (const line of await page.evaluate(longestLines)) {
        if (line.inTable) { worstCell = Math.max(worstCell, line.chars); continue; }
        blocks++;
        worst = Math.max(worst, line.chars);
        if (line.chars > LIMIT) over.push(`${rel || 'home'} @${width}: ${line.chars.toFixed(1)} chars  ${line.text}`);
      }
    }
    await ctx.close();
  }
  await browser.close();
  console.log(`wrapped text blocks: ${blocks} on ${PAGES.length} pages x ${WIDTHS.length} widths | longest line: ${worst.toFixed(1)} chars (limit ${LIMIT}) | over limit: ${over.length}`);
  console.log(`longest wrapped line inside a table cell: ${worstCell.toFixed(1)} chars (reported, not enforced)`);
  over.slice(0, 20).forEach(line => console.log('  -', line));
  process.exit(over.length ? 1 : 0);
})();
