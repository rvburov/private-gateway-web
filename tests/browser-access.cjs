/* Полный сценарий на отдельной тестовой БД. Секреты только в игнорируемой локальной fixture. */
const { createRequire } = require('node:module');
const { resolve } = require('node:path');
const { readFileSync, writeFileSync, existsSync, mkdirSync } = require('node:fs');
const { createHmac, randomBytes } = require('node:crypto');
const assert = require('node:assert/strict');
const projectRequire = createRequire(resolve(__dirname, '../frontend/package.json'));
const { chromium } = projectRequire('@playwright/test');
const fixturePath = resolve('.localdata/browser-fixture.json');
const fixture = JSON.parse(readFileSync(fixturePath, 'utf8'));
const base = process.env.PGWEB_BROWSER_URL || 'http://127.0.0.1:5173';
assert.equal(new URL(base).hostname, '127.0.0.1', 'Only isolated loopback test environment');
assert.ok(fixture.email.endsWith('@example.test'), 'Only a synthetic test administrator');
function saveFixture() { writeFileSync(fixturePath, JSON.stringify(fixture), { mode: 0o600 }); }
function totp(secret, step) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of secret.replace(/=|\s/g, '').toUpperCase()) bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(step));
  const hash = createHmac('sha1', key).update(counter).digest();
  const offset = hash.at(-1) & 15;
  return String((hash.readUInt32BE(offset) & 0x7fffffff) % 1000000).padStart(6, '0');
}
async function nextAdminCode(page) {
  const step = Math.max(Math.floor(Date.now() / 30000), (fixture.lastStep || 0) + 1);
  const delay = Math.max(0, (step - 1) * 30000 + 100 - Date.now());
  if (delay) await page.waitForTimeout(delay);
  fixture.lastStep = step; saveFixture();
  return totp(fixture.secret, step);
}
async function enroll(page, secret, previous = false) {
  const step = Math.floor(Date.now() / 30000) - (previous ? 1 : 0);
  await page.locator('.login-otp-box').first().fill(totp(secret, step));
  const response = page.waitForResponse(r => r.url().endsWith('/api/auth/2fa/setup/confirm'));
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  const confirmed = await response; assert.equal(confirmed.status(), 200, '2FA enrollment');
  const result = await confirmed.json();
  assert.equal(result.recovery_codes.length, 8);
  await page.getByRole('checkbox', { name: 'I have saved the recovery codes' }).check();
  await page.getByRole('button', { name: 'Go to account', exact: true }).click();
  await page.waitForURL('**/downloads');
  return { codes: result.recovery_codes, step };
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'],
    executablePath: process.env.PGWEB_CHROMIUM_EXECUTABLE || (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined) });
  const output = resolve('artifacts/browser'); mkdirSync(output, { recursive: true });
  const errors = [];
  try {
    const admin = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    admin.on('pageerror', e => errors.push(e.message));
    await admin.goto(`${base}/login`);
    await admin.locator('#auth-email').fill(fixture.email);
    await admin.locator('#auth-password').fill(fixture.password);
    let setupResponse;
    if (!fixture.secret) setupResponse = admin.waitForResponse(r => r.url().endsWith('/api/auth/2fa/setup'));
    await admin.getByRole('button', { name: 'Sign in', exact: true }).click();
    if (!fixture.secret) {
      const response = await setupResponse; assert.equal(response.status(), 200);
      fixture.secret = (await response.json()).secret;
      saveFixture();
      const result = await enroll(admin, fixture.secret, true);
      fixture.recovery = result.codes; fixture.lastStep = result.step; saveFixture();
    } else {
      await admin.getByRole('button', { name: 'Use a recovery code', exact: true }).click();
      await admin.locator('#auth-recovery').fill(fixture.recovery.shift()); saveFixture();
      await admin.getByRole('button', { name: 'Open account', exact: true }).click();
      await admin.waitForURL('**/downloads');
    }
    await admin.getByRole('link', { name: 'Invitations', exact: true }).click();
    await admin.getByRole('button', { name: 'Create invitation', exact: true }).click();
    const dialog = admin.getByRole('dialog');
    const memberEmail = `browser-member-${Date.now()}@example.test`;
    await dialog.getByLabel('Email address', { exact: true }).fill(memberEmail);
    await dialog.getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    await dialog.getByRole('button', { name: 'Create invitation', exact: true }).click();
    const invite = await dialog.getByLabel('One-time code', { exact: true }).inputValue();
    assert.ok(invite.startsWith('PG-'));
    await dialog.getByRole('button', { name: 'Done', exact: true }).click();

    const member = await browser.newPage({ viewport: { width: 390, height: 1000 } });
    member.on('pageerror', e => errors.push(e.message));
    await member.goto(`${base}/register`);
    await member.locator('#auth-invite').fill(invite);
    await member.locator('#auth-email').fill(memberEmail);
    await member.locator('#auth-name').fill('Browser Test Member');
    const memberPassword = randomBytes(24).toString('hex');
    await member.locator('#auth-password').fill(memberPassword);
    const setup = member.waitForResponse(r => r.url().endsWith('/api/auth/2fa/setup'));
    await member.locator('.auth-submit').click();
    const setupResult = await setup; assert.equal(setupResult.status(), 200, 'Invite registration');
    const memberEnrollment = await enroll(member, (await setupResult.json()).secret);
    await member.getByRole('heading', { name: 'Your Gateway. On every device.' }).waitFor();
    // Заголовок появляется до ответа /api/downloads; кнопки считаются после загрузки сетки.
    await member.locator('.ac-download-grid').waitFor();
    assert.equal(await member.getByRole('button', { name: 'Not available yet', exact: true }).count(), 4);
    assert.equal((await member.request.get(`${base}/api/admin/members`)).status(), 403);
    assert.equal((await member.request.get(`${base}/api/admin/downloads`)).status(), 403);
    assert.equal((await member.request.get(`${base}/api/downloads`)).status(), 200);
    await member.screenshot({ path: resolve(output, 'account-390.png'), fullPage: true });

    // Вход приложения тем же аккаунтом: токен только в заголовке, cookie сайта его не заменяет
    const appLogin = await member.request.post(`${base}/api/app/login`, { data: {
      email: memberEmail, password: memberPassword, recovery_code: memberEnrollment.codes[0],
      device: { uid: 'browser-test-device-0001', name: 'Browser Test Laptop', platform: 'linux', app_version: '0.0.0-test' } } });
    assert.equal(appLogin.status(), 200, 'App login');
    const appToken = (await appLogin.json()).token;
    assert.equal((await member.request.get(`${base}/api/app/status`)).status(), 401);
    assert.equal((await member.request.get(`${base}/api/app/status`, { headers: { Authorization: `Bearer ${appToken}` } })).status(), 200);
    await member.getByRole('link', { name: 'Devices', exact: true }).click();
    await member.getByRole('heading', { name: 'Your devices' }).waitFor();
    await member.getByText('This browser', { exact: true }).waitFor();
    await member.getByText('Browser Test Laptop', { exact: true }).waitFor();
    assert.equal(await member.locator('.ac-device-count').nth(1).textContent(), '1 of 3 in use');
    await member.screenshot({ path: resolve(output, 'devices-390.png'), fullPage: true });
    const overflow = await member.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, 'No horizontal scroll on the devices page');

    await admin.getByRole('link', { name: 'Members', exact: true }).click();
    await admin.getByLabel('Search members', { exact: true }).fill(memberEmail);
    await admin.getByRole('button', { name: 'Search', exact: true }).click();
    await admin.getByRole('button', { name: 'Details: Browser Test Member', exact: true }).click();
    // Администратор видит устройство приложения участника и задает ему личный лимит
    await admin.getByRole('dialog').getByText('Browser Test Laptop', { exact: true }).waitFor();
    await admin.getByRole('button', { name: 'Change device limit', exact: true }).click();
    await admin.getByRole('dialog').getByLabel('Device limit', { exact: true }).fill('1');
    await admin.getByRole('dialog').getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    const limited = admin.waitForResponse(r => r.url().includes('/api/admin/members/') && r.request().method() === 'PATCH');
    await admin.getByRole('button', { name: 'Confirm', exact: true }).click();
    assert.equal((await limited).status(), 200, 'Personal device limit');
    const secondDevice = await member.request.post(`${base}/api/app/login`, { data: {
      email: memberEmail, password: memberPassword, recovery_code: memberEnrollment.codes[1],
      device: { uid: 'browser-test-device-0002', name: 'Browser Test Phone', platform: 'android', app_version: '0.0.0-test' } } });
    assert.equal(secondDevice.status(), 409, 'Device limit reached');
    await admin.getByRole('dialog').waitFor({ state: 'detached' });
    await admin.getByRole('button', { name: 'Details: Browser Test Member', exact: true }).click();
    await admin.getByRole('dialog').getByText('1 of 1 in use', { exact: true }).waitFor();
    await admin.screenshot({ path: resolve(output, 'member-devices-1440.png'), fullPage: true });
    await admin.getByRole('button', { name: 'Download history', exact: true }).click();
    await admin.waitForURL('**/admin/downloads?user=*');
    await admin.getByRole('heading', { name: 'Download log' }).waitFor();
    await admin.getByRole('heading', { name: 'No downloads yet' }).waitFor();
    await admin.getByRole('link', { name: 'Members', exact: true }).click();
    await admin.getByLabel('Search members', { exact: true }).fill(memberEmail);
    await admin.getByRole('button', { name: 'Search', exact: true }).click();
    await admin.getByRole('button', { name: 'Details: Browser Test Member', exact: true }).click();
    await admin.getByRole('button', { name: 'Revoke access', exact: true }).click();
    await admin.getByRole('dialog').getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    const revoked = admin.waitForResponse(r => r.url().includes('/api/admin/members/') && r.request().method() === 'PATCH');
    await admin.getByRole('button', { name: 'Confirm', exact: true }).click();
    assert.equal((await revoked).status(), 200);
    assert.equal((await member.request.get(`${base}/api/me`)).status(), 401);
    assert.equal((await member.request.get(`${base}/api/downloads`)).status(), 401);
    assert.equal((await member.request.get(`${base}/api/app/status`, { headers: { Authorization: `Bearer ${appToken}` } })).status(), 401);
    await member.reload(); await member.waitForURL('**/login');
    await admin.screenshot({ path: resolve(output, 'members-1440.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: 1, failed: 0, skipped: 0,
      scenario: 'real invitation, registration, 2FA enrollment, downloads, RBAC, app device login, device page, personal device limit, download log, immediate access revocation', syntheticData: true }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
