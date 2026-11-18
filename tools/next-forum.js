// The colorectal surgeon forum, end to end (H7 #129): visitors and unverified members see only how to join; a
// verified member's first thread waits for moderation; the de-identification check is required; signed and anonymous
// posts; likes, reports, edit and delete; the maintainer approves, looks up an anonymous author, and pins a thread;
// keyboard and 360px phone use; axe on every forum page; noindex everywhere.
// Usage: node tools/next-forum.js <Next.js origin> <API base>
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (local demo key), DATABASE_URL (local; grants membership and admin).
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { chromium } = require('playwright');
const { signInLink } = require('./sign-in-link');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
const API = (process.argv[3] || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };
const step = message => console.log(`- ${message}`);
const run = Date.now().toString(36);
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

const psql = statement => execFileSync('psql', [process.env.DATABASE_URL, '-qtAc', statement]).toString().trim();
const literal = text => `'${text.replace(/'/g, "''")}'`;
const verify = name => psql(`update app.accounts set surgeon_since = now() where display_name = ${literal(name)}`);

async function signedIn(browser, name, viewport) {
  const context = await browser.newContext(viewport ? { viewport } : {});
  context.setDefaultTimeout(15000);
  const page = await context.newPage();
  await page.goto(await signInLink(ORIGIN, `${name.toLowerCase().replace(/\W/g, '-')}-${run}@example.test`));
  await page.waitForURL(/\/account\/\?welcome=1/);
  await page.getByRole('textbox', { name: '顯示名稱' }).fill(name);
  await page.getByRole('button', { name: '儲存' }).click();
  await page.waitForURL(`${ORIGIN}/`);
  return page;
}

const tokenOf = page => page.evaluate(() => JSON.parse(localStorage.getItem(
  Object.keys(localStorage).find(k => k.endsWith('-auth-token')))).access_token);

async function axe(page, label, selector = 'main') {
  await page.addScriptTag({ content: AXE });
  const result = await page.evaluate(([tags, root]) => axe.run(document.querySelector(root),
    { runOnly: { type: 'tag', values: tags } }), [TAGS, selector]);
  check(result.violations.length === 0,
    `axe ${label}: ${result.violations.map(v => `${v.id} ${v.nodes[0].target}`).join('; ')}`);
}

async function noindex(page, path) {
  const response = await page.goto(`${ORIGIN}${path}`);
  check(/noindex/.test(response.headers()['x-robots-tag'] || ''), `${path}: no X-Robots-Tag noindex`);
  check(/no-store/.test(response.headers()['cache-control'] || ''), `${path}: shared caching allowed`);
  const robots = await page.locator('meta[name="robots"]').getAttribute('content');
  check(/noindex/.test(robots || ''), `${path}: no robots noindex meta`);
}

async function write(page, { title, body, anonymous = false, confirm = true }) {
  if (title !== undefined) await page.getByLabel('標題', { exact: true }).fill(title);
  await page.getByLabel(title !== undefined ? '內容' : '你的回覆', { exact: true }).fill(body);
  await page.getByRole('radio', { name: anonymous ? /^匿名/ : /^署名/ }).check();
  const box = page.getByRole('checkbox', { name: '我確認內容不含可識別病人的資訊' });
  if (confirm) await box.check(); else await box.uncheck();
  await page.getByRole('button', { name: title !== undefined ? '發表話題' : '送出回覆' }).click();
}

let browser;
(async () => {
  browser = await chromium.launch();

  step('visitor: only the explanation, never indexed or cached');
  const visitor = await (await browser.newContext()).newPage();
  await noindex(visitor, '/forum/');
  await visitor.getByText('論壇只開放給通過驗證的大腸直腸外科會員').waitFor();
  check(await visitor.getByRole('link', { name: '登入' }).last().getAttribute('href') === '/login/?next=%2Fforum%2F',
    'visitor: login link does not return to the forum');
  await axe(visitor, 'forum gate');
  const sitemap = await (await fetch(`${ORIGIN}/sitemap.xml`)).text();
  check(!sitemap.includes('/forum'), 'sitemap lists the forum');
  check((await fetch(`${API}/forum/threads`)).status === 404, 'API: visitor does not get 404');

  step('member without verification sees how to apply');
  const aName = `Dr A ${run}`;
  const a = await signedIn(browser, aName, { width: 360, height: 800 });
  await a.goto(`${ORIGIN}/forum/`);
  await a.getByText('你還不是大腸直腸外科會員').waitFor();
  check(await a.getByRole('link', { name: '開新話題' }).count() === 0, 'unverified member sees the forum');

  step('verified member: first thread needs the de-identification check, then waits for moderation');
  verify(aName);
  await a.goto(`${ORIGIN}/forum/new/`);
  await noindex(a, '/forum/new/');
  const firstTitle = `Watch and wait after TNT ${run}`;
  await write(a, { title: firstTitle, body: 'How long do you follow a clinical complete response?', confirm: false });
  await a.getByText('送出前請確認內容不含可識別病人的資訊。').waitFor();
  await a.getByRole('checkbox', { name: '我確認內容不含可識別病人的資訊' }).check();
  await a.getByRole('button', { name: '發表話題' }).dblclick();
  await a.getByText('你在論壇的第一篇貼文要等維護者審核').waitFor();
  check(psql(`select count(*) from app.forum_posts where title = ${literal(firstTitle)}`) === '1',
    'double submit created more than one thread');
  await a.goto(`${ORIGIN}/forum/`);
  await a.getByRole('heading', { name: '只有你看得到的話題' }).waitFor();
  await a.getByText(firstTitle).waitFor();
  check(!(await a.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)),
    'forum overflows at 360px');

  step('another verified member does not see the pending thread');
  const bName = `Dr B ${run}`;
  const b = await signedIn(browser, bName);
  verify(bName);
  await b.goto(`${ORIGIN}/forum/`);
  await b.getByRole('link', { name: '開新話題' }).waitFor();
  check(await b.getByText(firstTitle).count() === 0, 'pending thread visible to another member');

  step('maintainer approves the first thread with a reason');
  const mName = `Moderator ${run}`;
  const m = await signedIn(browser, mName);
  psql(`update app.accounts set is_admin = true where display_name = ${literal(mName)}`);
  await b.goto(`${ORIGIN}/admin/forum/`);
  await b.getByText('需要管理者權限。').waitFor();
  await m.goto(`${ORIGIN}/admin/forum/`);
  const queued = m.locator('section[aria-labelledby="forum-queue"] .comment', { hasText: firstTitle });
  await queued.getByRole('button', { name: '公開' }).click();
  await queued.getByText('請先寫下處理原因').waitFor();
  await queued.getByLabel(/處理原因/).fill('Fine to discuss');
  await queued.getByRole('button', { name: '公開' }).click();
  await queued.waitFor({ state: 'detached' });

  step('trusted now: the next thread publishes and opens directly');
  await a.goto(`${ORIGIN}/forum/new/`);
  const secondTitle = `Lateral nodes after CRT ${run}`;
  await write(a, { title: secondTitle, body: 'Do you dissect persistent lateral nodes?' });
  await a.waitForURL(/\/forum\/[0-9a-f-]{36}\/$/);
  await a.getByRole('heading', { name: secondTitle }).waitFor();
  const secondPath = new URL(a.url()).pathname;
  await noindex(a, secondPath);
  await a.getByRole('heading', { name: secondTitle }).waitFor();
  check((await a.title()).indexOf(secondTitle) === -1, 'thread title leaks into the HTML title');

  step('B replies anonymously; the first reply waits and only B sees it');
  await b.goto(`${ORIGIN}${secondPath}`);
  await b.locator('.comment', { hasText: 'Do you dissect' }).getByText(aName).waitFor();
  const anonymousReply = `Only if they stay above 7 mm ${run}`;
  await write(b, { body: anonymousReply, anonymous: true });
  await b.getByText('你在論壇的第一篇貼文要等維護者審核').waitFor();
  await b.locator('[aria-label="只有你看得到的回覆"]').getByText(anonymousReply).waitFor();
  await a.reload();
  await a.getByRole('heading', { name: secondTitle }).waitFor();
  check(await a.getByText(anonymousReply).count() === 0, 'pending reply visible to the thread author');

  step('maintainer looks up the anonymous author (recorded), approves, and pins the thread');
  await m.reload();
  const pendingReply = m.locator('section[aria-labelledby="forum-queue"] .comment', { hasText: anonymousReply });
  await pendingReply.getByText(`回覆「${secondTitle}」`).waitFor();
  check(await pendingReply.getByText(bName).count() === 0, 'anonymous author shown by default');
  await pendingReply.getByLabel(/處理原因/).fill('Checking a first-time poster');
  await pendingReply.getByRole('button', { name: '查看作者' }).click();
  await pendingReply.getByText(`作者：${bName}`).waitFor();
  await pendingReply.getByRole('button', { name: '公開' }).click();
  await pendingReply.waitFor({ state: 'detached' });
  const row = m.locator('section[aria-labelledby="forum-all"] .comment', { hasText: secondTitle });
  await row.getByLabel(/處理原因/).fill('Useful question for everyone');
  await row.getByRole('button', { name: '置頂' }).click();
  await row.getByText('置頂', { exact: true }).waitFor();
  await axe(m, 'forum moderation');
  const audit = psql(`select string_agg(e.action::text, ',' order by e.id) from app.forum_moderation_events e
    join app.forum_posts p on p.id = e.post_id where p.title = ${literal(secondTitle)} or p.body = ${literal(anonymousReply)}`);
  check(audit === 'reveal_author,publish,pin', `audit trail ${audit}`);

  step('A sees the anonymous reply without a name; the API never carries it');
  await a.reload();
  const shown = a.locator('.comment', { hasText: anonymousReply });
  await shown.getByText('匿名醫師').waitFor();
  const detail = await a.evaluate(async ([api, path]) => {
    const key = Object.keys(localStorage).find(k => k.endsWith('-auth-token'));
    const token = JSON.parse(localStorage.getItem(key)).access_token;
    const id = path.split('/')[2];
    return (await fetch(`${api}/forum/threads/${id}`, { headers: { Authorization: `Bearer ${token}` } })).text();
  }, [API, secondPath]);
  check(detail.includes(anonymousReply) && !detail.includes(bName), 'anonymous reply leaks the name');

  step('B likes and reports; the pinned thread leads the list');
  await b.goto(`${ORIGIN}/forum/`);
  await b.locator('[aria-label="置頂話題"]').getByText(secondTitle).waitFor();
  await b.goto(`${ORIGIN}${secondPath}`);
  const opener = b.locator('.comment', { hasText: 'Do you dissect' });
  const liked = b.waitForResponse(r => r.url().endsWith('/likes') && r.request().method() === 'PUT');
  await opener.getByRole('button', { name: /^讚/ }).click();
  check((await liked).ok(), 'like failed');
  await b.reload();
  await b.locator('.comment', { hasText: 'Do you dissect' }).locator('button[aria-pressed="true"]').waitFor();
  const reload = b.locator('.comment', { hasText: 'Do you dissect' });
  await reload.getByRole('button', { name: '檢舉' }).click();
  await reload.getByLabel('檢舉原因').fill('Possibly identifiable');
  await reload.getByRole('button', { name: '送出檢舉' }).click();
  await reload.getByText('已收到檢舉，維護者會處理。').waitFor();
  check(await reload.getByRole('button', { name: '修改' }).count() === 0, 'B can edit A\'s post');

  step('keyboard only: B replies');
  const keyboard = `By keyboard ${run}`;
  await b.getByLabel('你的回覆').focus();
  await b.keyboard.type(keyboard);
  await b.keyboard.press('Tab');  // identity radios
  await b.keyboard.press('Tab');  // de-identification check
  await b.keyboard.press('Space');
  await b.keyboard.press('Tab');
  await b.keyboard.press('Enter');
  await b.getByText('已發布。').waitFor();
  await b.locator('.comment', { hasText: keyboard }).waitFor();

  step('authors edit and delete their own posts');
  const mine = b.locator('[aria-label="回覆"] .comment', { hasText: keyboard });
  await mine.getByRole('button', { name: '修改' }).click();
  await mine.getByLabel('修改內容').fill(`${keyboard} (edited)`);
  await mine.getByRole('button', { name: '儲存' }).click();
  const edited = b.locator('[aria-label="回覆"] .comment', { hasText: `${keyboard} (edited)` });
  await edited.getByText('（已編輯）').waitFor();
  await edited.getByRole('button', { name: '刪除' }).click();
  await edited.getByRole('button', { name: '確定刪除' }).click();
  await edited.waitFor({ state: 'detached' });

  step('accessibility of the forum pages, light and dark');
  for (const colorScheme of ['light', 'dark']) {
    await b.emulateMedia({ colorScheme });
    await b.goto(`${ORIGIN}/forum/`);
    await b.locator('[aria-label="置頂話題"]').waitFor();
    await axe(b, `list ${colorScheme}`);
    await b.goto(`${ORIGIN}${secondPath}`);
    await b.getByRole('heading', { name: secondTitle }).waitFor();
    await axe(b, `thread ${colorScheme}`);
    await b.goto(`${ORIGIN}/forum/new/`);
    await b.getByLabel('標題', { exact: true }).waitFor();
    await axe(b, `new thread ${colorScheme}`);
  }

  step('the reported thread reaches the queue; hiding it takes it out of view');
  await m.reload();
  const reported = m.locator('section[aria-labelledby="forum-queue"] .comment', { hasText: secondTitle });
  await reported.getByText('Possibly identifiable').waitFor();
  await reported.getByLabel(/處理原因/).fill('Removed: identifiable');
  await reported.getByRole('button', { name: '隱藏' }).click();
  await reported.waitFor({ state: 'detached' });
  await b.goto(`${ORIGIN}${secondPath}`);
  await b.getByRole('heading', { name: '找不到這個話題' }).waitFor();
  const bToken = await tokenOf(b);
  check((await fetch(`${API}/admin/forum-posts`, { headers: { Authorization: `Bearer ${bToken}` } })).status === 403,
    'non-admin reaches the forum queue');

  console.log('forum: visitor and unverified gates, noindex, pending first thread, de-identification check, single send,');
  console.log('       approval, trusted posting, anonymous reply without a name, author lookup with audit, pinning,');
  console.log('       likes, reports, keyboard reply, edit and delete, 360px, axe light and dark, hiding');
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => browser?.close());
