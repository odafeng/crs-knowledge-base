// Following papers for the daily comment digest, end to end (G8 #119): the follow button in a paper's discussion,
// commenting follows, the account page's list and digest switch, and the unsubscribe page a digest links to, which
// changes nothing until its button is pressed. Axe on the account section and the unsubscribe page, light and dark.
// Usage: node tools/next-follows.js <Next.js origin>
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (local demo key), DATABASE_URL (local; reads the state and the digest token).
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const { chromium } = require('playwright');
const { signInLink } = require('./sign-in-link');

const ORIGIN = (process.argv[2] || 'http://127.0.0.1:3000').replace(/\/$/, '');
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

async function axe(page, label, selector = 'main') {
  await page.addScriptTag({ content: AXE });
  const result = await page.evaluate(([tags, root]) => axe.run(document.querySelector(root),
    { runOnly: { type: 'tag', values: tags } }), [TAGS, selector]);
  check(result.violations.length === 0,
    `axe ${label}: ${result.violations.map(v => `${v.id} ${v.nodes[0].target}`).join('; ')}`);
}

const discussion = page => page.locator('section.comments');
const followButton = page => discussion(page).getByRole('button', { name: /追蹤新留言/ });
const followed = id => psql(`select count(*) from app.paper_follows where account_id = '${id}' and paper_id = '${PAPER_ID}'`);
const digestOn = id => psql(`select comment_digest from app.accounts where id = '${id}'`);

let browser;
(async () => {
  browser = await chromium.launch();

  step('a visitor gets no follow button');
  const visitor = await (await browser.newContext()).newPage();
  await visitor.goto(`${ORIGIN}${PAPER}`);
  await discussion(visitor).getByText(/還沒有留言|讀者留言/).first().waitFor();
  check(await followButton(visitor).count() === 0, 'visitor sees the follow button');

  step('a reader follows from the discussion, at 360px');
  const name = `Follower ${run}`;
  const f = await signedIn(browser, name, { width: 360, height: 800 });
  const id = psql(`select id from app.accounts where display_name = ${literal(name)}`);
  await f.goto(`${ORIGIN}${PAPER}`);
  await followButton(f).waitFor();
  check(await followButton(f).getAttribute('aria-pressed') === 'false', 'follow button starts pressed');
  await followButton(f).click();
  await discussion(f).getByText(/已追蹤。有新留言時，隔天早上會寄一封彙整信/).waitFor();
  check(await followButton(f).getAttribute('aria-pressed') === 'true', 'follow button not pressed after following');
  check(followed(id) === '1', 'following stored nothing');
  check(!(await f.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)),
    'discussion overflows at 360px');

  step('the account page lists it, can stop following it, and turns the digest off and on');
  await f.goto(`${ORIGIN}/account/`);
  const list = f.locator('section[aria-labelledby="follows-title"]');
  await list.getByRole('link', { name: /Neoadjuvant nivo \+ ipi/ }).waitFor();
  await axe(f, 'followed papers 360px', 'section[aria-labelledby="follows-title"]');
  await list.getByRole('button', { name: /取消追蹤/ }).click();
  await list.getByText('還沒有追蹤任何文獻。').waitFor();
  check(followed(id) === '0', 'unfollowing from the account page left the follow');
  const digest = list.getByRole('checkbox', { name: /每天早上寄一封信/ });
  await digest.uncheck();
  await list.getByText('已關閉每日留言通知').waitFor();
  check(digestOn(id) === 'f', 'turning the digest off did not stick');
  await digest.check();
  await list.getByText('已開啟每日留言通知。').waitFor();
  check(digestOn(id) === 't', 'turning the digest on did not stick');

  step('commenting follows the paper, and the button shows it at once');
  await f.goto(`${ORIGIN}${PAPER}`);
  await followButton(f).waitFor();
  await discussion(f).getByLabel('你的留言').fill(`Following this one ${run}`);
  await discussion(f).getByRole('button', { name: '送出留言' }).click();
  await discussion(f).getByText('第一則留言要等維護者審核後才會公開').waitFor();
  await discussion(f).getByRole('button', { name: '已追蹤新留言' }).waitFor();
  check(followed(id) === '1', 'commenting did not follow the paper');

  step('a digest link changes nothing until the button is pressed');
  const token = psql(`select digest_token from app.accounts where id = '${id}'`);
  const reader = await (await browser.newContext()).newPage();  // the mail opens in a browser that is not signed in
  const response = await reader.goto(`${ORIGIN}/unsubscribe/?t=${token}&paper=${PAPER_ID}`);
  check(/no-store|private/.test(response.headers()['cache-control'] || ''), 'unsubscribe page may be cached');
  check(/noindex/.test(await reader.locator('meta[name="robots"]').getAttribute('content') || ''),
    'unsubscribe page is indexable');
  await reader.getByRole('button', { name: '取消追蹤這篇' }).waitFor();
  await reader.getByText(/Neoadjuvant nivo \+ ipi/).first().waitFor();
  check(followed(id) === '1', 'opening the link unfollowed before the button was pressed');
  for (const colorScheme of ['light', 'dark']) {
    await reader.emulateMedia({ colorScheme });
    await reader.reload();
    await reader.getByRole('button', { name: '取消追蹤這篇' }).waitFor();
    await axe(reader, `unsubscribe page ${colorScheme}`);
  }
  await reader.getByRole('button', { name: '取消追蹤這篇' }).click();
  await reader.getByText(/已取消追蹤/).waitFor();
  check(followed(id) === '0', 'the unfollow link did not unfollow');

  step('the stop link turns the digest off; a broken link says so');
  await reader.goto(`${ORIGIN}/unsubscribe/?t=${token}`);
  await reader.getByRole('button', { name: '停止每日留言通知' }).click();
  await reader.getByText(/已停止每日留言通知/).waitFor();
  check(digestOn(id) === 'f', 'the stop link did not turn the digest off');
  await reader.goto(`${ORIGIN}/unsubscribe/?t=00000000-0000-4000-8000-000000000000`);
  await reader.getByRole('button', { name: '停止每日留言通知' }).click();
  await reader.getByText('這個連結無效或已失效。', { exact: false }).waitFor();
  await reader.goto(`${ORIGIN}/unsubscribe/`);
  await reader.getByText('這個連結無效或已失效。', { exact: false }).waitFor();

  console.log('follows: visitor without button, follow and unfollow, account list and digest switch, commenting');
  console.log('         follows, unsubscribe links only on press, broken links, 360px, axe light and dark');
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => browser?.close());
