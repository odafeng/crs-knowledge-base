// Sign-in, the account page, sign-out and switching accounts on the running Next.js site (D1 #67).
// Usage: node tools/next-auth.js <Next.js origin> <API base, e.g. http://127.0.0.1:8000/api/v1>
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (local demo key), MAILPIT_URL (optional: also sends a real email).
const { chromium } = require('playwright');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
const API = (process.argv[3] || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const { SUPABASE_URL, SUPABASE_SERVICE_KEY, MAILPIT_URL } = process.env;
const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };
const step = message => console.log(`- ${message}`);
const run = Date.now().toString(36);

async function admin(path, body) {
  const response = await fetch(`${SUPABASE_URL}/auth/v1${path}`, {
    method: 'POST',
    headers: { apikey: SUPABASE_SERVICE_KEY, Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} ${response.status} ${await response.text()}`);
  return response.json();
}

/** A one-time sign-in link for `email`, as the email template builds it. */
async function signInLink(email) {
  const link = await admin('/admin/generate_link', { type: 'magiclink', email });
  return `${ORIGIN}/auth/callback/?token_hash=${link.hashed_token ?? link.properties.hashed_token}&type=email`;
}

async function mailedLink(email) {
  for (let i = 0; i < 40; i++) {
    const search = await (await fetch(`${MAILPIT_URL}/api/v1/search?query=${encodeURIComponent(`to:"${email}"`)}`)).json();
    if (search.messages?.length) {
      const message = await (await fetch(`${MAILPIT_URL}/api/v1/message/${search.messages[0].ID}`)).json();
      const href = message.HTML.match(/href="([^"]*\/auth\/callback\/[^"]*)"/)?.[1];
      return href?.replace(/&amp;/g, '&');
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return null;
}

const accountLabel = page => page.locator('.site-header .account-link').getAttribute('aria-label');
const sessionKeys = page => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('sb-')));

async function setName(page, name) {
  await page.getByRole('textbox', { name: '顯示名稱' }).fill(name);
  await page.getByRole('button', { name: '儲存' }).click();
}

let browser;
(async () => {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required');
  browser = await chromium.launch();
  const context = async () => {
    const created = await browser.newContext();
    created.setDefaultTimeout(15000);
    return created;
  };

  // 1. A visitor: same HTML for everyone, a sign-in entry that returns to the current page.
  step('visitor');
  const first = await context();
  const page = await first.newPage();
  const html = await (await page.request.get(`${ORIGIN}/papers/niche2/`)).text();
  check(!html.includes('帳號：') && !html.includes('access_token'), 'visitor: page HTML mentions an account');
  await page.goto(`${ORIGIN}/papers/niche2/`);
  await page.locator('.site-header .account-link[aria-label="登入"]').waitFor();
  check((await page.locator('.site-header .account-link').getAttribute('href')) === '/login/?next=%2Fpapers%2Fniche2%2F',
    'visitor: sign-in link does not return to the page');
  for (const path of ['/account/', '/auth/callback/']) {
    const cache = (await page.request.get(`${ORIGIN}${path}`)).headers()['cache-control'];
    check(cache === 'private, no-store', `headers: ${path} Cache-Control is ${cache}`);
  }
  check((await page.request.get(`${API}/me`)).status() === 401, 'api: /me without a token is not 401');

  // 2. Reader A asks for a link on this device and opens it on another (a fresh browser context).
  step('reader A signs in on another device');
  const emailA = `reader-a-${run}@example.test`;
  let linkA;
  await page.click('.site-header .account-link');
  await page.waitForURL(`${ORIGIN}/login/?next=%2Fpapers%2Fniche2%2F`);
  if (MAILPIT_URL) {
    await page.getByLabel('Email').fill(emailA);
    await page.getByRole('button', { name: '寄送登入連結' }).click();
    await page.getByText(`登入連結已寄到 ${emailA}`).waitFor();
    linkA = await mailedLink(emailA);
    check(linkA?.startsWith(`${ORIGIN}/auth/callback/?token_hash=`), `email: link is ${linkA}`);
  } else {
    linkA = await signInLink(emailA);
  }
  const other = await context();
  const device = await other.newPage();
  await device.goto(linkA);
  await device.waitForURL(/\/account\/\?welcome=1/);
  check(!device.url().includes('token_hash'), 'callback: token left in the address bar');
  await device.getByText('歡迎！請先設定公開顯示名稱').waitFor();
  check((await device.getByRole('textbox', { name: '顯示名稱' }).inputValue()) === '', 'account A: name field not empty for a new reader');
  await setName(device, '   ');
  await device.getByText('請填寫顯示名稱').waitFor();
  await setName(device, 'Reader A');
  await device.waitForURL(`${ORIGIN}/`);
  await device.locator('.site-header .account-link--signed-in').waitFor();
  check((await accountLabel(device)) === '帳號：Reader A', `header A: ${await accountLabel(device)}`);

  // The token works against the API; a tampered one does not.
  const token = await device.evaluate(() => {
    const key = Object.keys(localStorage).find(k => k.startsWith('sb-') && k.endsWith('-auth-token'));
    return JSON.parse(localStorage.getItem(key)).access_token;
  });
  const me = await device.request.get(`${API}/me`, { headers: { Authorization: `Bearer ${token}` } });
  check(me.status() === 200 && (await me.json()).displayName === 'Reader A', 'api: /me for A');
  check(me.headers()['cache-control'] === 'private, no-store', 'api: /me is cacheable');
  const tampered = `${token.slice(0, -6)}${token.endsWith('AAAAAA') ? 'BBBBBB' : 'AAAAAA'}`;
  check((await device.request.get(`${API}/me`, { headers: { Authorization: `Bearer ${tampered}` } })).status() === 401,
    'api: tampered token accepted');

  // A used link cannot sign anyone in again.
  step('used link');
  const replay = await (await context()).newPage();
  await replay.goto(linkA);
  await replay.getByText('這個登入連結無效或已過期').waitFor();

  step('sign out, then reader B');
  // 3. Sign out, then reader B on the same device sees nothing of A.
  await device.goto(`${ORIGIN}/account/`);
  await device.getByRole('button', { name: '登出' }).click();
  await device.waitForURL(`${ORIGIN}/`);
  await device.locator('.site-header .account-link[aria-label="登入"]').waitFor();
  check((await sessionKeys(device)).length === 0, `sign-out: session left in storage ${await sessionKeys(device)}`);

  await device.goto(await signInLink(`reader-b-${run}@example.test`));
  await device.waitForURL(/\/account\/\?welcome=1/);
  check((await device.getByRole('textbox', { name: '顯示名稱' }).inputValue()) === '', 'switch: B sees A\'s display name');
  check(await device.getByText(`reader-b-${run}@example.test`).count() === 1, 'switch: B\'s email not shown');
  check(await device.getByText(emailA).count() === 0, 'switch: A\'s email still shown');
  await setName(device, 'Reader B');
  await device.waitForURL(`${ORIGIN}/`);
  await device.locator('.site-header .account-link--signed-in').waitFor();
  check((await accountLabel(device)) === '帳號：Reader B', `switch: header shows ${await accountLabel(device)}`);

  step('service worker cache');
  // Nothing about either reader reaches the service worker cache.
  await device.goto(`${ORIGIN}/papers/niche2/`);
  await device.waitForFunction(() => navigator.serviceWorker.controller !== null);
  const cached = await device.evaluate(async () => (await Promise.all((await caches.keys()).map(async name =>
    (await (await caches.open(name)).keys()).map(r => r.url)))).flat());
  check(cached.length > 0, 'cache: service worker cached nothing, so the check below proves nothing');
  const leaked = cached.filter(url => /\/(auth|account|me|api)(\/|$)|token/.test(url));
  check(leaked.length === 0, `cache: ${leaked.join(', ')}`);

  console.log(`auth: ${MAILPIT_URL ? 'emailed' : 'generated'} link on another device, name required, sign-out clears the session,`);
  console.log('      account switch isolated, used and tampered tokens refused, nothing private cached');
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => browser?.close());
