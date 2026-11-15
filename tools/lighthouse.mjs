import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import lighthouse from 'lighthouse';
import * as chromeLauncher from 'chrome-launcher';

const ROOT = process.argv[2];
const TYPES = { '.webmanifest': 'application/manifest+json', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.html': 'text/html; charset=utf-8', '.json': 'application/json', '.js': 'text/javascript', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  let rel = decodeURIComponent(new URL(req.url, 'http://x').pathname).replace('/crs-knowledge-base/', ''); if (rel === '' || rel.endsWith('/')) rel += 'index.html';
  const file = path.join(ROOT, rel);
  if (!file.startsWith(ROOT) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end('nf'); }
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'text/plain' });
  fs.createReadStream(file).pipe(res);
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const chrome = await chromeLauncher.launch({ chromeFlags: ['--headless=new', '--no-sandbox', '--disable-gpu'] });
const pages = { home: 'crs-knowledge-base/', story: 'crs-knowledge-base/news/ifebemtinib-garsorasib/', news: 'crs-knowledge-base/news/', topic: 'crs-knowledge-base/mcrc/msi-h/', paper: 'crs-knowledge-base/papers/bw-nejm-2025/', robotic: 'crs-knowledge-base/robotic/tme/' };
const out = {};
for (const [name, rel] of Object.entries(pages)) {
  const r = await lighthouse(`http://127.0.0.1:${port}/${rel}`, { port: chrome.port, output: 'json', logLevel: 'error', onlyCategories: ['performance', 'accessibility', 'best-practices', 'seo'] });
  const l = r.lhr;
  const a = id => l.audits[id];
  out[name] = {
    scores: Object.fromEntries(Object.entries(l.categories).map(([k, v]) => [k, Math.round(v.score * 100)])),
    metrics: { FCP: a('first-contentful-paint').displayValue, LCP: a('largest-contentful-paint').displayValue, TBT: a('total-blocking-time').displayValue, CLS: a('cumulative-layout-shift').displayValue, SI: a('speed-index').displayValue },
    bytes: a('total-byte-weight').displayValue,
    failed: Object.values(l.audits).filter(x => x.score !== null && x.score < 0.9 && x.scoreDisplayMode !== 'informative' && x.scoreDisplayMode !== 'manual' && x.scoreDisplayMode !== 'notApplicable').map(x => `${x.id}${x.displayValue ? ' (' + x.displayValue + ')' : ''}`),
    env: { formFactor: l.configSettings.formFactor, throttling: l.configSettings.throttlingMethod, lhVersion: l.lighthouseVersion },
  };
}
console.log(JSON.stringify(out, null, 1));
await chrome.kill();
server.close();
