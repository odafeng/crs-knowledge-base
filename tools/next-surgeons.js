// Colorectal surgeon verification, end to end (H5 #127): a member applies from the account page, the form checks
// its fields, a pending application can be withdrawn, non-admins cannot reach the review page, the maintainer approves
// and later revokes, a second applicant is rejected. Each decision deletes the application, leaves an audit row
// without its contents, and opens or closes the forum. Axe on the account section and the review page, light and dark.
// Usage: node tools/next-surgeons.js <Next.js origin> <API base>
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (local demo key), DATABASE_URL (local; grants the admin flag).
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
const idOf = name => psql(`select id from app.accounts where display_name = ${literal(name)}`);
const applications = id => psql(`select count(*) from app.surgeon_applications where account_id = '${id}'`);
const events = id => psql(`select string_agg(action, ',' order by id) from app.surgeon_verification_events
  where account_id = '${id}'`);

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

const section = page => page.locator('section[aria-labelledby="surgeon-title"]');

async function apply(page, { realName, hospital, digits }) {
  await page.goto(`${ORIGIN}/account/`);
  const form = section(page);
  await form.getByRole('button', { name: '送出申請' }).waitFor();
  await form.getByLabel('真實姓名').fill(realName);
  await form.getByLabel('執業院所').fill(hospital);
  await form.getByLabel('證書字號後三碼').fill(digits);
  await form.getByRole('button', { name: '送出申請' }).click();
}

async function forumOpen(page) {
  await page.goto(`${ORIGIN}/forum/`);
  await page.locator('main').getByText(/開新話題|你還不是大腸直腸外科會員|你的驗證申請正在審核中/).first().waitFor();
  return (await page.getByRole('link', { name: '開新話題' }).count()) > 0;
}

let browser;
(async () => {
  browser = await chromium.launch();

  step('a member sees the application form; the form checks its fields');
  const aName = `Applicant A ${run}`;
  const a = await signedIn(browser, aName, { width: 360, height: 800 });
  const aId = idOf(aName);
  await apply(a, { realName: '王測試', hospital: '測試醫院', digits: '12' });
  await section(a).getByText('證書字號後三碼請填三個數字。').waitFor();
  check(applications(aId) === '0', 'an invalid application was stored');
  await axe(a, 'application form 360px', 'section[aria-labelledby="surgeon-title"]');
  check(!(await a.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)),
    'account page overflows at 360px');

  step('a pending application can be withdrawn, which deletes it');
  await apply(a, { realName: '王測試', hospital: '測試醫院', digits: '123' });
  await section(a).getByText('申請審核中').waitFor();
  check(applications(aId) === '1', 'the application was not stored');
  check(!(await forumOpen(a)), 'a pending applicant reaches the forum');
  await a.getByText('你的驗證申請正在審核中').waitFor();
  await a.goto(`${ORIGIN}/account/`);
  await section(a).getByRole('button', { name: '撤回申請' }).click();
  await section(a).getByText('已撤回申請，填寫的資料已刪除。').waitFor();
  check(applications(aId) === '0', 'withdrawing left the application');
  check(events(aId) === '', 'withdrawing wrote an audit row');

  step('the applicant applies again; a non-admin cannot review');
  await apply(a, { realName: '王測試', hospital: '測試醫院', digits: '123' });
  await section(a).getByText('申請審核中').waitFor();
  await a.goto(`${ORIGIN}/admin/surgeons/`);
  await a.getByText('需要管理者權限。').waitFor();
  const aToken = await tokenOf(a);
  check((await fetch(`${API}/admin/surgeon-applications`, { headers: { Authorization: `Bearer ${aToken}` } }))
    .status === 403, 'non-admin reaches the application queue');

  step('the maintainer sees the details and approves');
  const mName = `Reviewer ${run}`;
  const m = await signedIn(browser, mName);
  psql(`update app.accounts set is_admin = true where display_name = ${literal(mName)}`);
  await m.goto(`${ORIGIN}/admin/surgeons/`);
  const pending = m.locator('section[aria-labelledby="pending-title"] li', { hasText: aName });
  await pending.getByText('王測試').waitFor();
  check(await pending.getByText('測試醫院').count() === 1, 'the review does not show the hospital');
  for (const colorScheme of ['light', 'dark']) {
    await m.emulateMedia({ colorScheme });
    await axe(m, `review page ${colorScheme}`);
  }
  await pending.getByRole('button', { name: '核准' }).click();
  await m.getByText(`已核准 ${aName}，申請資料已刪除。`).waitFor();
  await m.locator('section[aria-labelledby="members-title"] li', { hasText: aName }).waitFor();
  check(applications(aId) === '0', 'approving left the application');
  check(events(aId) === 'approve', `audit after approval: ${events(aId)}`);
  check(psql(`select count(*) from app.surgeon_verification_events where account_id = '${aId}'
    and decided_by = '${idOf(mName)}'`) === '1', 'the audit row does not name the reviewer');

  step('the approved member sees it and enters the forum');
  await a.goto(`${ORIGIN}/account/`);
  await section(a).getByText(/你是大腸直腸外科會員/).waitFor();
  check(await forumOpen(a), 'an approved member cannot open the forum');

  step('the maintainer revokes; the forum closes again');
  await m.reload();
  await m.locator('section[aria-labelledby="members-title"] li', { hasText: aName })
    .getByRole('button', { name: '撤銷資格' }).click();
  await m.getByText(`已撤銷 ${aName} 的會員資格。`).waitFor();
  check(events(aId) === 'approve,revoke', `audit after revoking: ${events(aId)}`);
  check(!(await forumOpen(a)), 'a revoked member still reaches the forum');
  await a.goto(`${ORIGIN}/account/`);
  await section(a).getByRole('button', { name: '送出申請' }).waitFor();

  step('a second applicant is rejected: the details go, the form comes back');
  const bName = `Applicant B ${run}`;
  const b = await signedIn(browser, bName);
  const bId = idOf(bName);
  await apply(b, { realName: '李測試', hospital: '另一家醫院', digits: '456' });
  await section(b).getByText('申請審核中').waitFor();
  await m.reload();
  await m.locator('section[aria-labelledby="pending-title"] li', { hasText: bName })
    .getByRole('button', { name: '退回' }).click();
  await m.getByText(`已退回 ${bName}，申請資料已刪除。`).waitFor();
  check(applications(bId) === '0', 'rejecting left the application');
  check(events(bId) === 'reject', `audit after rejection: ${events(bId)}`);
  check(psql(`select count(*) from app.accounts where id = '${bId}' and surgeon_since is not null`) === '0',
    'a rejected applicant became a member');
  await b.goto(`${ORIGIN}/account/`);
  await section(b).getByRole('button', { name: '送出申請' }).waitFor();
  check(!(await forumOpen(b)), 'a rejected applicant reaches the forum');

  console.log('surgeons: field check, withdraw, non-admin refused, approve with audit, forum opens, revoke closes it,');
  console.log('          reject deletes the details, 360px, axe on the form and the review page light and dark');
  console.log('problems:', problems.length);
  problems.forEach(problem => console.log('  -', problem));
  if (problems.length) process.exitCode = 1;
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
}).finally(() => browser?.close());
