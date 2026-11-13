/* Полный сценарий на отдельной тестовой БД. Секреты только в игнорируемой локальной fixture. */
const { createRequire } = require('node:module');
const { resolve } = require('node:path');
const { readFileSync, writeFileSync, existsSync, mkdirSync, statSync } = require('node:fs');
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
    // Шаг пароля общий для всех: «запомнить устройство» появляется только на шаге кода 2FA
    assert.equal(await admin.getByRole('checkbox', { name: /Remember this device/ }).count(), 0);
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
      await admin.getByRole('checkbox', { name: /Remember this device/ }).waitFor();
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

    // Участник на телефоне Android: вход без 2FA, карточка Android первой, скачивание .apk
    const androidAgent = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36';
    const phone = await browser.newContext({ viewport: { width: 390, height: 1000 }, userAgent: androidAgent, isMobile: true, hasTouch: true, acceptDownloads: true });
    const member = await phone.newPage();
    member.on('pageerror', e => errors.push(e.message));
    await member.goto(`${base}/register`);
    await member.locator('#auth-invite').fill(invite);
    await member.locator('#auth-email').fill(memberEmail);
    await member.locator('#auth-name').fill('Browser Test Member');
    const memberPassword = randomBytes(24).toString('hex');
    await member.locator('#auth-password').fill(memberPassword);
    const registered = member.waitForResponse(r => r.url().endsWith('/api/auth/register'));
    await member.locator('.auth-submit').click();
    const registration = await registered; assert.equal(registration.status(), 200, 'Invite registration');
    assert.equal((await registration.json()).status, 'ok', 'Member registration opens the account without 2FA');
    await member.waitForURL('**/downloads');
    await member.getByRole('heading', { name: 'Your Gateway. On every device.' }).waitFor();
    // Заголовок появляется до ответа /api/downloads; кнопки считаются после загрузки сетки.
    await member.locator('.ac-download-grid').waitFor();
    const catalog = (await (await member.request.get(`${base}/api/downloads`)).json()).items;
    const published = catalog.filter(item => item.available && item.platform !== 'ios').length;
    assert.equal(await member.getByRole('button', { name: 'Not available yet', exact: true }).count(), 4 - published);
    const firstCard = member.locator('.ac-download-card').first();
    assert.equal(await firstCard.getAttribute('data-platform'), 'android', 'Android first on an Android phone');
    assert.match(await firstCard.getAttribute('class'), /is-featured/);
    assert.equal(await member.locator('.ac-download-card.is-featured').count(), 1);
    await firstCard.getByText('After downloading, open the file and allow installation from this source.', { exact: true }).waitFor();
    assert.equal((await member.request.get(`${base}/api/admin/members`)).status(), 403);
    assert.equal((await member.request.get(`${base}/api/admin/downloads`)).status(), 403);
    await member.screenshot({ path: resolve(output, 'downloads-android-390.png'), fullPage: true });
    const android = catalog.find(item => item.platform === 'android');
    if (android.available) {
      const link = member.getByRole('link', { name: 'Download for Android', exact: true });
      assert.match(await link.getAttribute('class'), /primary/);
      const [download] = await Promise.all([member.waitForEvent('download'), link.click()]);
      assert.equal(download.suggestedFilename(), android.filename, 'Phone keeps the .apk name');
      assert.ok(download.suggestedFilename().endsWith('.apk'));
      assert.equal(statSync(await download.path()).size, android.size_bytes, 'Full file on the phone');
      const headers = (await member.request.get(`${base}${android.url}`, { headers: { 'Accept-Encoding': 'gzip, br, zstd' } })).headers();
      assert.equal(headers['content-type'], 'application/vnd.android.package-archive');
      assert.equal(headers['content-length'], String(android.size_bytes));
      assert.ok(!headers['content-encoding'], 'No compression of the package');
      assert.match(headers['content-disposition'], /^attachment; filename=".+\.apk"; filename\*=UTF-8''/);
    } else console.log('Android file is not published on this stand: the phone download step was skipped');

    // Вход приложения тем же аккаунтом: участнику код не нужен, присланный (как у 0.2.0) не проверяется
    const appDevice = { uid: 'browser-test-device-0001', name: 'Browser Test Laptop', platform: 'linux', app_version: '0.0.0-test' };
    const appLogin = await member.request.post(`${base}/api/app/login`, { data: { email: memberEmail, password: memberPassword, code: '123456', device: appDevice } });
    assert.equal(appLogin.status(), 200, 'App login');
    const appToken = (await appLogin.json()).token;
    assert.equal((await member.request.get(`${base}/api/app/status`)).status(), 401);
    assert.equal((await member.request.get(`${base}/api/app/status`, { headers: { Authorization: `Bearer ${appToken}` } })).status(), 200);
    await member.getByRole('link', { name: 'Devices', exact: true }).click();
    await member.getByRole('heading', { name: 'Your devices' }).waitFor();
    await member.getByText('This browser', { exact: true }).waitFor();
    await member.getByText('Browser Test Laptop', { exact: true }).waitFor();
    assert.equal(await member.locator('.ac-device-count').nth(1).textContent(), '1 of 3 in use');
    await member.getByText('New devices in 30 days: 1 of 3', { exact: true }).waitFor();
    await member.screenshot({ path: resolve(output, 'devices-390.png'), fullPage: true });
    const overflow = await member.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, 'No horizontal scroll on the devices page');

    // Своя смена пароля: этот браузер остается, приложение выходит, повторный вход — не новое устройство
    await member.getByRole('button', { name: 'Change password', exact: true }).click();
    const passwordDialog = member.getByRole('dialog');
    assert.equal(await passwordDialog.getByLabel('Your current 2FA code').count(), 0, 'No 2FA for a member');
    const newPassword = randomBytes(24).toString('hex');
    await passwordDialog.getByLabel('Current password', { exact: true }).fill(memberPassword);
    await passwordDialog.getByLabel('New password', { exact: true }).fill(newPassword);
    await member.screenshot({ path: resolve(output, 'change-password-390.png') });
    const changed = member.waitForResponse(r => r.url().endsWith('/api/me/password'));
    await passwordDialog.getByRole('button', { name: 'Change password', exact: true }).click();
    assert.equal((await changed).status(), 200, 'Password change');
    await member.getByText('Password changed. Other sign-ins have ended.', { exact: true }).waitFor();
    assert.equal((await member.request.get(`${base}/api/me`)).status(), 200, 'This browser stays signed in');
    assert.equal((await member.request.get(`${base}/api/app/status`, { headers: { Authorization: `Bearer ${appToken}` } })).status(), 401);
    const relogin = await member.request.post(`${base}/api/app/login`, { data: { email: memberEmail, password: newPassword, device: appDevice } });
    assert.equal(relogin.status(), 200, 'App relogin with the new password');
    const reloginToken = (await relogin.json()).token;
    const changes = (await (await member.request.get(`${base}/api/me/devices`)).json()).device_changes;
    assert.deepEqual(changes, { used: 1, limit: 3, days: 30 }, 'Relogin of the same installation is not a new device');

    await admin.getByRole('link', { name: 'Members', exact: true }).click();
    await admin.getByLabel('Search members', { exact: true }).fill(memberEmail);
    await admin.getByRole('button', { name: 'Search', exact: true }).click();
    await admin.getByText('Password sign-in', { exact: true }).waitFor();
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
      email: memberEmail, password: newPassword,
      device: { uid: 'browser-test-device-0002', name: 'Browser Test Phone', platform: 'android', app_version: '0.0.0-test' } } });
    assert.equal(secondDevice.status(), 409, 'Device limit reached');
    assert.equal((await secondDevice.json()).error.code, 'device_limit');
    // Администратору в приложении нужен код 2FA: без него 401 code_required, ничего не тратится
    const adminApp = await admin.request.post(`${base}/api/app/login`, { data: { email: fixture.email, password: fixture.password, device: { uid: 'browser-test-admin-0001', name: 'Admin Laptop', platform: 'windows', app_version: '0.0.0-test' } } });
    assert.equal(adminApp.status(), 401);
    assert.equal((await adminApp.json()).error.code, 'code_required');
    await admin.getByRole('dialog').waitFor({ state: 'detached' });
    await admin.getByRole('button', { name: 'Details: Browser Test Member', exact: true }).click();
    await admin.getByRole('dialog').getByText('1 of 1 in use', { exact: true }).waitFor();
    await admin.screenshot({ path: resolve(output, 'member-devices-1440.png'), fullPage: true });
    await admin.getByRole('button', { name: 'Download history', exact: true }).click();
    await admin.waitForURL('**/admin/downloads?user=*');
    await admin.getByRole('heading', { name: 'Download log' }).waitFor();
    if (android.available) await admin.getByText('Android 0.0.0-test', { exact: true }).first().waitFor();
    else await admin.getByRole('heading', { name: 'No downloads yet' }).waitFor();
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
    assert.equal((await member.request.get(`${base}/api/app/status`, { headers: { Authorization: `Bearer ${reloginToken}` } })).status(), 401);
    await member.reload(); await member.waitForURL('**/login');
    await admin.screenshot({ path: resolve(output, 'members-1440.png'), fullPage: true });

    // Полное удаление участника: в журнале скачиваний остается «Удаленный участник»
    await admin.getByRole('dialog').waitFor({ state: 'detached' });
    await admin.getByRole('button', { name: 'Details: Browser Test Member', exact: true }).click();
    await admin.getByRole('button', { name: 'Delete member', exact: true }).click();
    await admin.getByRole('dialog').getByText(/This cannot be undone/).waitFor();
    await admin.getByRole('dialog').getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    await admin.screenshot({ path: resolve(output, 'delete-member-1440.png') });
    const deleted = admin.waitForResponse(r => r.url().endsWith('/delete') && r.request().method() === 'POST');
    await admin.getByRole('dialog').getByRole('button', { name: 'Delete member', exact: true }).click();
    assert.equal((await deleted).status(), 204, 'Member deleted');
    await admin.getByRole('heading', { name: 'No members found' }).waitFor();
    if (android.available) {
      await admin.getByRole('link', { name: 'Download log', exact: true }).click();
      await admin.getByText('Deleted member', { exact: true }).first().waitFor();
    }
    const gone = await member.request.post(`${base}/api/auth/login`, { data: { email: memberEmail, password: newPassword }, headers: { 'X-CSRF-Token': (await (await member.request.get(`${base}/api/auth/csrf`)).json()).csrf_token } });
    assert.equal(gone.status(), 401, 'Deleted member cannot sign in');

    // Удаление приглашения из списка
    await admin.getByRole('link', { name: 'Invitations', exact: true }).click();
    await admin.getByRole('button', { name: 'Create invitation', exact: true }).click();
    const extraEmail = `browser-extra-${Date.now()}@example.test`;
    await admin.getByRole('dialog').getByLabel('Email address', { exact: true }).fill(extraEmail);
    await admin.getByRole('dialog').getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    await admin.getByRole('dialog').getByRole('button', { name: 'Create invitation', exact: true }).click();
    await admin.getByRole('dialog').getByLabel('One-time code', { exact: true }).waitFor();
    await admin.getByRole('dialog').getByRole('button', { name: 'Done', exact: true }).click();
    await admin.getByText(extraEmail, { exact: true }).waitFor();
    await admin.screenshot({ path: resolve(output, 'invites-1440.png'), fullPage: true });
    await admin.getByRole('button', { name: `Delete: ${extraEmail}`, exact: true }).click();
    await admin.getByRole('dialog').getByLabel('Your current 2FA code', { exact: true }).fill(await nextAdminCode(admin));
    const inviteDeleted = admin.waitForResponse(r => r.url().endsWith('/delete') && r.request().method() === 'POST');
    await admin.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click();
    assert.equal((await inviteDeleted).status(), 204, 'Invitation deleted');
    await admin.getByText(extraEmail, { exact: true }).waitFor({ state: 'detached' });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: 1, failed: 0, skipped: 0,
      scenario: 'administrator 2FA, member invitation without 2FA, Android-first downloads and .apk download on a phone, RBAC, app login without a member code, device page and change counter, own password change, personal device limit, admin code_required, download log, access revocation, member and invitation deletion', syntheticData: true }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
