// Reader discussion on a paper page, end to end (D3 #69): visitor, first comment waiting for moderation, signed and
// anonymous comments, the author's edit and delete, another reader's report, failure and retry, double submit,
// limits and resends (D4), and the moderation queue (D5).
// Usage: node tools/next-comments.js <Next.js origin> <API base>
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (local demo key), DATABASE_URL (local; stands in for moderation, D5).
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { chromium } = require('playwright');
const { signInLink } = require('./sign-in-link');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
const API = (process.argv[3] || 'http://127.0.0.1:8000/api/v1').replace(/\/$/, '');
const PAPER = '/papers/niche2/';
const PAPER_ID = 'niche2';
const problems = [];
const check = (ok, message) => { if (!ok) problems.push(message); };
const step = message => console.log(`- ${message}`);
const run = Date.now().toString(36);
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'];

const psql = statement => execFileSync('psql', [process.env.DATABASE_URL, '-qtAc', statement]).toString().trim();
const literal = text => `'${text.replace(/'/g, "''")}'`;

/** Approves a pending comment, as the maintainer will in D5. */
const approve = commentBody => psql(`update app.comments set status = 'published' where body = ${literal(commentBody)}`);

async function signedIn(browser, name, viewport) {
  const context = await browser.newContext(viewport ? { viewport } : {});
  context.setDefaultTimeout(15000);
  const page = await context.newPage();
  await page.goto(await signInLink(ORIGIN, `${name.toLowerCase().replace(/\W/g, '-')}-${run}@example.test`));
  await page.waitForURL(/\/account\/\?welcome=1/);
  await page.getByRole('textbox', { name: '顯示名稱' }).fill(name);
  await page.getByRole('button', { name: '儲存' }).click();
  await page.waitForURL(`${ORIGIN}/`);
  await page.goto(`${ORIGIN}${PAPER}`);
  await page.getByRole('heading', { name: '讀者討論' }).waitFor();
  return page;
}

const section = page => page.locator('section.comments');
const publicComments = async () => (await (await fetch(`${API}/papers/${PAPER_ID}/comments?limit=100`)).json()).items;

async function post(page, body, { anonymous = false } = {}) {
  await section(page).getByLabel('你的留言').fill(body);
  await section(page).getByRole('radio', { name: anonymous ? /^匿名/ : /^署名/ }).check();
  await section(page).getByRole('button', { name: '送出留言' }).click();
}

let browser;
(async () => {
  browser = await chromium.launch();

  step('visitor');
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`${ORIGIN}${PAPER}`);
  await section(visitor).getByText(/還沒有留言|讀者留言/).first().waitFor();
  const gate = section(visitor).getByRole('link', { name: '登入' });
  check(await gate.getAttribute('href') === `/login/?next=${encodeURIComponent(PAPER)}`, 'visitor: login link does not return');
  check(await section(visitor).getByLabel('你的留言').count() === 0, 'visitor: comment box shown');

  step('reader A: first comment waits for moderation; double submit sends once');
  const a = await signedIn(browser, `Reader A ${run}`, { width: 360, height: 800 });
  const first = `First thoughts ${run}`;
  await section(a).getByLabel('你的留言').fill(first);
  await section(a).getByRole('button', { name: '送出留言' }).dblclick();
  await section(a).getByText('第一則留言要等維護者審核後才會公開').waitFor();
  await section(a).getByText('等待審核，只有你看得到').waitFor();
  check((await publicComments()).every(c => c.body !== first), 'pending comment is public');
  const mine = await a.evaluate(async api => {
    const key = Object.keys(localStorage).find(k => k.endsWith('-auth-token'));
    const token = JSON.parse(localStorage.getItem(key)).access_token;
    return (await (await fetch(`${api}/me/comments`, { headers: { Authorization: `Bearer ${token}` } })).json()).items;
  }, API);
  check(mine.filter(o => o.comment.body === first).length === 1, `double submit created ${mine.length} comments`);
  check(!(await a.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)),
    'reader A: discussion overflows at 360px');

  step('approval, then signed and anonymous comments publish directly');
  approve(first);
  await a.reload();
  const signedItem = section(a).locator('.comment', { hasText: first });
  await signedItem.getByText(`Reader A ${run}`).waitFor();
  await signedItem.getByText('你的留言').waitFor();
  const anonymousBody = `Quietly, ${run}`;
  await post(a, anonymousBody, { anonymous: true });
  await section(a).getByText('已發布。').waitFor();
  const anonymousItem = section(a).locator('.comment', { hasText: anonymousBody });
  await anonymousItem.getByText('匿名讀者').waitFor();
  const listed = (await publicComments()).find(c => c.body === anonymousBody);
  check(listed && listed.displayName === null && !JSON.stringify(listed).includes('Reader A'), 'anonymous comment leaks the name');

  step('author edits; a failed send keeps the text and a retry works');
  await anonymousItem.getByRole('button', { name: '修改' }).click();
  await anonymousItem.getByLabel('修改留言').fill(`${anonymousBody} (edited)`);
  await anonymousItem.getByRole('button', { name: '儲存' }).click();
  await section(a).locator('.comment', { hasText: `${anonymousBody} (edited)` }).getByText('（已編輯）').waitFor();

  const retry = `Network blip ${run}`;
  await a.route(`${API}/papers/${PAPER_ID}/comments`, route =>
    route.request().method() === 'POST' ? route.abort('internetdisconnected') : route.continue());
  await post(a, retry);
  await section(a).getByText('送出失敗，請檢查網路後再試一次。你寫的內容還在。').waitFor();
  check(await section(a).getByLabel('你的留言').inputValue() === retry, 'failed send lost the text');
  await a.unroute(`${API}/papers/${PAPER_ID}/comments`);
  await section(a).getByRole('button', { name: '送出留言' }).click();
  await section(a).getByText('已發布。').waitFor();
  await section(a).locator('.comment', { hasText: retry }).waitFor();

  step('reader B: sees no edit or delete on A\'s comments, can report once');
  const b = await signedIn(browser, `Reader B ${run}`);
  const othersItem = section(b).locator('.comment', { hasText: first });
  await othersItem.waitFor();
  check(await othersItem.getByRole('button', { name: '修改' }).count() === 0, 'B can edit A\'s comment');
  check(await othersItem.getByRole('button', { name: '刪除' }).count() === 0, 'B can delete A\'s comment');
  await othersItem.getByRole('button', { name: '檢舉' }).click();
  await othersItem.getByRole('button', { name: '送出檢舉' }).click();
  await othersItem.getByText('請寫下檢舉原因').waitFor();
  await othersItem.getByLabel('檢舉原因').fill('Off topic');
  await othersItem.getByRole('button', { name: '送出檢舉' }).click();
  await othersItem.getByText('已收到檢舉，維護者會處理。').waitFor();
  await othersItem.getByRole('button', { name: '檢舉' }).click();
  await othersItem.getByLabel('檢舉原因').fill('Again');
  await othersItem.getByRole('button', { name: '送出檢舉' }).click();
  await othersItem.getByText('你已經檢舉過這則留言。').waitFor();

  step('likes (H1): B likes A\'s comment, it survives a reload, A only sees the count');
  const likeButton = othersItem.getByRole('button', { name: /^讚/ });
  const liked = b.waitForResponse(r => r.url().endsWith('/likes') && r.request().method() === 'PUT');
  await likeButton.click();
  check((await liked).ok(), 'likes: like request failed');
  await othersItem.locator('button[aria-pressed="true"]').waitFor();
  check((await likeButton.innerText()).includes('1'), `likes: count after liking is ${await likeButton.innerText()}`);
  await b.reload();
  const reloaded = section(b).locator('.comment', { hasText: first });
  await reloaded.locator('button[aria-pressed="true"]').waitFor();
  check((await publicComments()).find(c => c.body === first)?.likeCount === 1, 'likes: API count is not 1');
  await a.reload();
  const ownItem = section(a).locator('.comment', { hasText: first });
  await ownItem.getByText('1 個讚').waitFor();
  check(await ownItem.getByRole('button', { name: /^讚/ }).count() === 0, 'likes: author can like own comment');
  // The button updates before the request finishes; wait for the API's answer before checking it.
  const unliked = b.waitForResponse(r => r.url().endsWith('/likes') && r.request().method() === 'DELETE');
  await reloaded.getByRole('button', { name: /^讚/ }).click();
  check((await unliked).ok(), 'likes: unlike request failed');
  await reloaded.locator('button[aria-pressed="false"]').waitFor();
  check((await publicComments()).find(c => c.body === first)?.likeCount === 0, 'likes: unlike did not reach the API');

  step('author deletes after confirming');
  const retryItem = section(a).locator('.comment', { hasText: retry });
  await retryItem.getByRole('button', { name: '刪除' }).click();
  await retryItem.getByRole('button', { name: '取消' }).click();
  await retryItem.getByRole('button', { name: '刪除' }).click();
  await retryItem.getByRole('button', { name: '確定刪除' }).click();
  await section(a).locator('.comment', { hasText: retry }).waitFor({ state: 'detached' });
  check((await publicComments()).every(c => c.body !== retry), 'deleted comment still public');

  step('accessibility of the signed-in discussion, light and dark');
  for (const colorScheme of ['light', 'dark']) {
    await a.emulateMedia({ colorScheme });
    await a.reload();
    await section(a).locator('.comment').first().waitFor();
    await a.addScriptTag({ content: AXE });
    const result = await a.evaluate(tags => axe.run(document.querySelector('section.comments'),
      { runOnly: { type: 'tag', values: tags } }), TAGS);
    check(result.violations.length === 0, `axe ${colorScheme}: ${result.violations.map(v => `${v.id} ${v.nodes[0].target}`).join('; ')}`);
  }

  step('keyboard only: write and send a comment');
  const keyboard = `By keyboard ${run}`;
  await section(b).getByLabel('你的留言').focus();
  await b.keyboard.type(keyboard);
  await b.keyboard.press('Tab');
  await b.keyboard.press('Tab');
  await b.keyboard.press('Enter');
  await section(b).getByText(/已送出|已發布/).waitFor();

  step('a lost response then a resend makes one comment (D4)');
  const lost = `Lost response ${run}`;
  await b.route(`${API}/papers/${PAPER_ID}/comments`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fetch();  // the server stores it, the browser never hears back
    await route.abort('connectionreset');
  });
  await post(b, lost);
  await section(b).getByText('送出失敗，請檢查網路後再試一次。你寫的內容還在。').waitFor();
  await b.unroute(`${API}/papers/${PAPER_ID}/comments`);
  await section(b).getByRole('button', { name: '送出留言' }).click();
  await section(b).getByText(/已送出|已發布/).waitFor();
  check(psql(`select count(*) from app.comments where body = ${literal(lost)}`) === '1', 'resend created a duplicate');

  step('over the limit: the reader is told how long to wait, keeps the text, and can send later');
  let limited = false;
  for (let i = 0; i < 6 && !limited; i++) {
    await post(b, `Burst ${i} ${run}`);
    const outcome = section(b).getByText(/已送出|已發布|留言太頻繁/);
    await outcome.first().waitFor();
    limited = (await section(b).getByText(/留言太頻繁，請 \d+ 分鐘後再試。你寫的內容還在。/).count()) === 1;
  }
  check(limited, 'limit: never reached');
  const kept = await section(b).getByLabel('你的留言').inputValue();
  check(kept.startsWith('Burst '), 'limit: text lost');
  psql(`update app.comments set created_at = now() - interval '11 minutes' where author_id =
    (select author_id from app.comments where body = ${literal(lost)})`);
  await section(b).getByRole('button', { name: '送出留言' }).click();
  await section(b).getByText(/已送出|已發布/).waitFor();

  step('moderation (D5): only the admin sees the queue; reasons are required and recorded');
  await b.goto(`${ORIGIN}/admin/comments/`);
  await b.getByText('需要管理者權限。').waitFor();
  const bToken = await b.evaluate(() => JSON.parse(localStorage.getItem(
    Object.keys(localStorage).find(k => k.endsWith('-auth-token')))).access_token);
  const denied = await fetch(`${API}/admin/comments`, { headers: { Authorization: `Bearer ${bToken}` } });
  check(denied.status === 403, `moderation: non-admin API answer ${denied.status}`);
  const edited = `${anonymousBody} (edited)`;
  await b.goto(`${ORIGIN}${PAPER}`);
  const anonymousForB = section(b).locator('.comment', { hasText: edited });
  await anonymousForB.getByRole('button', { name: '檢舉' }).click();
  await anonymousForB.getByLabel('檢舉原因').fill('Unsourced claim');
  await anonymousForB.getByRole('button', { name: '送出檢舉' }).click();
  await anonymousForB.getByText('已收到檢舉，維護者會處理。').waitFor();

  const moderatorName = `Moderator ${run}`;
  const m = await signedIn(browser, moderatorName);
  psql(`update app.accounts set is_admin = true where display_name = ${literal(moderatorName)}`);
  await m.goto(`${ORIGIN}/admin/comments/`);
  const reportedAnonymous = m.locator('.comment', { hasText: edited });
  await reportedAnonymous.getByText('Unsourced claim').waitFor();
  check(await reportedAnonymous.getByText(`Reader A ${run}`).count() === 0, 'moderation: anonymous author shown by default');
  await reportedAnonymous.getByRole('button', { name: '查看作者' }).click();
  await reportedAnonymous.getByText('請先寫下處理原因').waitFor();
  await reportedAnonymous.getByLabel(/處理原因/).fill('Checking for repeat abuse');
  await reportedAnonymous.getByRole('button', { name: '查看作者' }).click();
  await reportedAnonymous.getByText(`作者：Reader A ${run}`).waitFor();

  await m.addScriptTag({ content: AXE });
  const queueAxe = await m.evaluate(tags => axe.run(document.querySelector('main'), { runOnly: { type: 'tag', values: tags } }), TAGS);
  check(queueAxe.violations.length === 0, `axe queue: ${queueAxe.violations.map(v => `${v.id} ${v.nodes[0].target}`).join('; ')}`);

  const reportedSigned = m.locator('.comment', { hasText: first });
  await reportedSigned.getByLabel(/處理原因/).fill('Off topic');
  await reportedSigned.getByRole('button', { name: '隱藏' }).click();
  await reportedSigned.waitFor({ state: 'detached' });
  check((await publicComments()).every(c => c.body !== first), 'moderation: hidden comment still public');

  const waiting = m.locator('.comment', { hasText: keyboard });
  await waiting.getByLabel(/處理原因/).fill('First comment is fine');
  await waiting.getByRole('button', { name: '公開' }).click();
  await waiting.waitFor({ state: 'detached' });
  check((await publicComments()).some(c => c.body === keyboard), 'moderation: approved comment not public');
  const audit = psql(`select string_agg(e.action::text, ',' order by e.id) from app.moderation_events e
    join app.comments c on c.id = e.comment_id where c.body in (${literal(edited)}, ${literal(first)}, ${literal(keyboard)})`);
  check(audit === 'reveal_author,hide,resolve_report,publish', `moderation: audit trail ${audit}`);

  // Weekly activity (G10 #121): counts for the maintainer only, never a list of readers.
  await m.goto(`${ORIGIN}/admin/stats/`);
  const thisWeek = m.locator('tr[aria-current="date"]');
  await thisWeek.waitFor();
  check(await m.locator('table.activity tbody tr').count() === 12, 'stats: not 12 weeks');
  const active = Number(await thisWeek.locator('.activity__count').innerText());
  check(active >= 2, `stats: ${active} active readers this week, expected at least the two in this run`);
  check(await m.getByText(`Reader A ${run}`).count() === 0, 'stats: a reader name is shown');
  await m.addScriptTag({ content: AXE });
  const statsAxe = await m.evaluate(tags => axe.run(document.querySelector('main'), { runOnly: { type: 'tag', values: tags } }), TAGS);
  check(statsAxe.violations.length === 0, `axe stats: ${statsAxe.violations.map(v => `${v.id} ${v.nodes[0].target}`).join('; ')}`);
  await a.goto(`${ORIGIN}/admin/stats/`);
  await a.getByText('需要管理者權限').waitFor();

  console.log('comments: visitor gate, pending first comment, single send on double click, approval, signed and anonymous,');
  console.log('          edit, failure keeps text and retry, others cannot edit or delete, report once, delete, keyboard,');
  console.log('          resend after a lost response, over the limit and recovery, likes, moderation with audit,');
  console.log('          weekly activity counts for the maintainer only');
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => browser?.close());
