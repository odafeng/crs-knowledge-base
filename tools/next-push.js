// Web Push on the Next.js site (C5 #95), against the local API and database, with no real push service:
//   1. the button appears and follows the subscription; turning push on stores exactly { endpoint, keys } through
//      the API (checked in the database), and the state survives a reload;
//   2. a push message delivered to the real service worker (Chrome DevTools Protocol) becomes a notification that
//      points at the story;
//   3. turning push off removes the row; no request ever goes to a push service, so nobody is notified.
// The browser's subscribe() is replaced by a stand-in: headless Chromium has no push service behind it.
// Usage: DATABASE_URL=... node tools/next-push.js http://127.0.0.1:3000   (built with NEXT_PUBLIC_PUSH_PUBLIC_KEY)
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const fs = require('node:fs');

const WEB = process.argv[2].replace(/\/$/, '');
const ENDPOINT = `https://fcm.googleapis.com/fcm/send/e2e-${Date.now()}`;
const KEYS = { p256dh: 'BEq92_TdZHWFumPXL2bSHnBMqQBmT_W8m21dM7uY3rkkXPMVrQbusl5OczVDTV0mymDHq9gvO-BlkPCo5biR1do', auth: 'e2e-auth-secret-123456' };
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];
const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };
const psql = statement => execFileSync('psql', [process.env.DATABASE_URL, '-qtAc', statement]).toString().trim();
const stored = () => psql(`select p256dh || ' ' || auth from app.push_subscriptions where endpoint = '${ENDPOINT}'`);

// Runs in the page before any site script: a PushManager that remembers its one subscription in localStorage.
function stubPush({ endpoint, keys }) {
  const key = 'e2e-push-subscription';
  const make = () => ({
    endpoint,
    toJSON: () => ({ endpoint, expirationTime: null, keys }),
    unsubscribe: async () => { localStorage.removeItem(key); return true; },
  });
  PushManager.prototype.getSubscription = async () => (localStorage.getItem(key) ? make() : null);
  PushManager.prototype.subscribe = async options => {
    if (!options.userVisibleOnly || !(options.applicationServerKey instanceof Uint8Array)) throw new Error('bad options');
    window.__pushKeyLength = options.applicationServerKey.length;
    localStorage.setItem(key, '1');
    return make();
  };
}

let browser;
(async () => {
  // The new headless mode: the older headless shell refuses the notification permission outright.
  browser = await chromium.launch({ channel: 'chromium' });
  const context = await browser.newContext({ viewport: { width: 360, height: 800 } });
  await context.grantPermissions(['notifications'], { origin: WEB });
  await context.addInitScript(stubPush, { endpoint: ENDPOINT, keys: KEYS });
  const pushServiceRequests = [];
  context.on('request', request => {
    if (/googleapis\.com|mozilla\.com|push\.apple\.com|windows\.com/.test(new URL(request.url()).hostname)) {
      pushServiceRequests.push(request.url());
    }
  });
  const page = await context.newPage();
  await page.goto(`${WEB}/subscribe/`);
  await page.evaluate(() => navigator.serviceWorker.ready);

  // 1. Turn push on.
  const button = page.getByRole('button', { name: '開啟推播' });
  await button.waitFor();
  check((await button.getAttribute('aria-pressed')) === 'false', 'button does not start unpressed');
  const saved = page.waitForResponse(r => r.url().endsWith('/push/subscription') && r.request().method() === 'PUT');
  await button.click();
  const response = await saved;
  check(response.status() === 204, `subscribe answered ${response.status()}`);
  check(JSON.stringify(response.request().postDataJSON()) === JSON.stringify({ endpoint: ENDPOINT, keys: KEYS }),
    'subscribe sent more or other than endpoint and keys');
  check(response.request().headers().authorization === undefined, 'subscribe carried a token');
  check(await page.evaluate(() => window.__pushKeyLength) === 65, 'VAPID key was not decoded to 65 bytes');
  await page.getByRole('button', { name: '關閉推播' }).waitFor();
  check(await page.getByRole('status').filter({ hasText: '推播已開啟' }).count() === 1, 'no confirmation shown');
  check(stored() === `${KEYS.p256dh} ${KEYS.auth}`, 'subscription not stored in the database');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  check(!overflow, 'subscribe page overflows at 360px');
  await page.addScriptTag({ content: AXE });
  const axe = await page.evaluate(tags => axe.run(document.querySelector('.alerts'), { runOnly: { type: 'tag', values: tags } }), TAGS);
  check(axe.violations.length === 0, `axe: ${axe.violations.map(v => `${v.id} ${v.nodes[0].target} ${v.nodes[0].any?.[0]?.message ?? ''}`).join('; ')}`);
  await page.reload();
  await page.getByRole('button', { name: '關閉推播' }).waitFor();

  // 2. A push message reaches the service worker and becomes a notification.
  const cdp = await context.newCDPSession(page);
  const registration = new Promise(resolve => cdp.on('ServiceWorker.workerRegistrationUpdated', ({ registrations }) => {
    const found = registrations.find(r => r.scopeURL === `${WEB}/` && !r.isDeleted);
    if (found) resolve(found.registrationId);
  }));
  await cdp.send('ServiceWorker.enable');
  const registrationId = await registration;
  const story = { title: 'E2E 新消息', body: '測試內容', url: '/news/e2e-story/', tag: 'e2e-story' };
  await cdp.send('ServiceWorker.deliverPushMessage', { origin: WEB, registrationId, data: JSON.stringify(story) });
  let shown = null;
  for (let i = 0; i < 50 && !shown; i++) {
    shown = await page.evaluate(async () => {
      const [found] = await (await navigator.serviceWorker.ready).getNotifications({ tag: 'e2e-story' });
      return found ? { title: found.title, body: found.body, url: found.data?.url } : null;
    });
    if (!shown) await page.waitForTimeout(200);
  }
  check(shown?.title === story.title && shown?.body === story.body && shown?.url === story.url,
    `notification was ${JSON.stringify(shown)}`);

  // 3. Turn push off.
  const removed = page.waitForResponse(r => r.url().endsWith('/push/subscription') && r.request().method() === 'DELETE');
  await page.getByRole('button', { name: '關閉推播' }).click();
  check((await removed).status() === 204, 'unsubscribe failed');
  await page.getByRole('button', { name: '開啟推播' }).waitFor();
  check(stored() === '', 'subscription still stored after turning push off');
  check(pushServiceRequests.length === 0, `requests went to a push service: ${pushServiceRequests.join(', ')}`);

  console.log('push: button state, subscribe stores endpoint and keys only, reload keeps state, notification from');
  console.log('      a delivered message, unsubscribe removes the row, no push service contacted, axe, 360px');
  console.log('problems:', problems.length);
  for (const problem of problems) console.log('  -', problem);
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => {
  browser?.close();
  try { psql(`delete from app.push_subscriptions where endpoint = '${ENDPOINT}'`); } catch { /* database gone */ }
});
