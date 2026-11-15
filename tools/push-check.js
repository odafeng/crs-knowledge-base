// Push, as far as a machine without a push service can check it:
//   1. the bell appears and its state follows the subscription;
//   2. turning push on registers the service worker and sends the store exactly { endpoint, p256dh, auth };
//   3. a push message reaches sw.js and becomes a notification that points at the story.
// The browser's own subscribe() is replaced by a stand-in: headless Chromium has no push service behind it.
// Usage: PUSH_PUBLIC_KEY=... PUSH_API=http://localhost:4173/rest python build.py ... --out site-push
//        node tools/push-check.js site-push
const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const SITE = path.resolve(process.argv[2]);
const PORT = 4173;
const BASE = '/crs-knowledge-base/';
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png' };
const calls = [];

const server = http.createServer((req, res) => {
  if (req.url.startsWith('/rest/rpc/')) {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => { calls.push({ name: req.url.split('/').pop(), apikey: req.headers.apikey, body: JSON.parse(body) }); res.writeHead(204).end(); });
    return;
  }
  let file = path.join(SITE, decodeURIComponent(new URL(req.url, 'http://x').pathname).replace(BASE, ''));
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  if (!fs.existsSync(file)) return res.writeHead(404).end('not found');
  res.writeHead(200, { 'content-type': TYPES[path.extname(file)] || 'text/plain' }).end(fs.readFileSync(file));
});

const standIn = () => {
  const subscription = {
    endpoint: 'https://fcm.googleapis.com/fcm/send/stand-in',
    toJSON() { return { endpoint: this.endpoint, keys: { p256dh: 'P256DH', auth: 'AUTH' } }; },
    unsubscribe: async () => { sessionStorage.removeItem('stand-in'); return true; },
  };
  PushManager.prototype.subscribe = async function (options) { window.__subscribeOptions = { userVisibleOnly: options.userVisibleOnly, keyLength: options.applicationServerKey.length }; sessionStorage.setItem('stand-in', '1'); return subscription; };
  PushManager.prototype.getSubscription = async () => (sessionStorage.getItem('stand-in') ? subscription : null);
};

(async () => {
  await new Promise(resolve => server.listen(PORT, '127.0.0.1', resolve));
  const origin = `http://localhost:${PORT}`;
  const browser = await chromium.launch({ channel: 'chromium' });  // full Chromium in headless mode: the headless shell has no notifications
  const context = await browser.newContext({ viewport: { width: 360, height: 780 } });
  await context.grantPermissions(['notifications'], { origin });
  const page = await context.newPage();
  await page.addInitScript(standIn);
  const failures = [];
  const expect = (label, ok, detail = '') => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ' | ' + detail : ''}`); if (!ok) failures.push(label); };

  await page.goto(origin + BASE + 'news/niche2-five-year/', { waitUntil: 'networkidle' });
  const bell = page.locator('header [data-push-toggle]');
  await page.waitForSelector('header [data-push-toggle][data-push-state]');
  expect('bell is shown, off', await bell.isVisible() && await bell.getAttribute('data-push-state') === 'off', await bell.getAttribute('aria-label'));

  await bell.click();
  await page.waitForFunction(() => document.querySelector('header [data-push-toggle]').dataset.pushState !== 'off' || document.querySelector('header [data-push-toggle]').disabled === false);
  await page.waitForTimeout(300);
  expect('turning it on sets the bell to on', await bell.getAttribute('data-push-state') === 'on' && await bell.getAttribute('aria-pressed') === 'true', await bell.getAttribute('aria-label'));
  const options = await page.evaluate(() => window.__subscribeOptions);
  expect('subscribe() got userVisibleOnly and a 65-byte key', options.userVisibleOnly === true && options.keyLength === 65, JSON.stringify(options));
  expect('the store received the subscription', calls.length === 1 && calls[0].name === 'push_subscribe' && JSON.stringify(calls[0].body) === JSON.stringify({ endpoint: 'https://fcm.googleapis.com/fcm/send/stand-in', p256dh: 'P256DH', auth: 'AUTH' }), JSON.stringify(calls[0]));
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  expect('service worker controls the whole site', scope === origin + BASE, scope);

  // Deliver a push message the way the browser would, through the DevTools protocol.
  const cdp = await context.newCDPSession(page);
  const registrations = [];
  cdp.on('ServiceWorker.workerRegistrationUpdated', event => registrations.push(...event.registrations));
  await cdp.send('ServiceWorker.enable');
  await page.waitForTimeout(300);
  const registration = registrations.find(r => r.scopeURL === scope);
  const story = { title: 'NICHE-2 五年追蹤：術前雙免疫後 111 例無一復發', body: '3 年無病存活與 5 年整體存活都是 100%。', url: 'news/niche2-five-year/', tag: 'niche2-five-year' };
  await cdp.send('ServiceWorker.deliverPushMessage', { origin, registrationId: registration.registrationId, data: JSON.stringify(story) });
  await page.waitForTimeout(500);
  const shown = await page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).map(n => ({ title: n.title, body: n.body, tag: n.tag, url: n.data.url, icon: n.icon })));
  expect('a push becomes one notification with the story', shown.length === 1 && shown[0].title === story.title && shown[0].body === story.body && shown[0].tag === story.tag, JSON.stringify(shown));
  const target = new URL(shown[0]?.url || '', scope).href;
  expect('tapping it opens the story', target === origin + BASE + 'news/niche2-five-year/' && fs.existsSync(path.join(SITE, 'news/niche2-five-year/index.html')), target);
  expect('notification icon exists', fs.existsSync(path.join(SITE, 'icons/icon-192.png')) && fs.existsSync(path.join(SITE, 'icons/badge-96.png')), shown[0]?.icon);

  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForSelector('header [data-push-toggle][data-push-state]');
  expect('after a reload the bell remembers it is on', await bell.getAttribute('data-push-state') === 'on');
  await bell.click();
  await page.waitForTimeout(500);
  expect('turning it off tells the store and resets the bell', await bell.getAttribute('data-push-state') === 'off' && calls.length === 2 && calls[1].name === 'push_unsubscribe' && calls[1].body.endpoint === 'https://fcm.googleapis.com/fcm/send/stand-in', JSON.stringify(calls[1]));

  await browser.close();
  server.close();
  console.log(failures.length ? `${failures.length} failed` : 'all push checks passed');
  process.exit(failures.length ? 1 : 0);
})();
