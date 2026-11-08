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
    await member.locator('#auth-password').fill(randomBytes(24).toString('hex'));
    const setup = member.waitForResponse(r => r.url().endsWith('/api/auth/2fa/setup'));
    await member.locator('.auth-submit').click();
    const setupResult = await setup; assert.equal(setupResult.status(), 200, 'Invite registration');
    await enroll(member, (await setupResult.json()).secret);
    await member.getByRole('heading', { name: 'Your Gateway. On every device.' }).waitFor();
    assert.equal(await member.getByRole('button', { name: 'Not available yet', exact: true }).count(), 4);
    assert.equal((await member.request.get(`${base}/api/admin/members`)).status(), 403);
    assert.equal((await member.request.get(`${base}/api/downloads`)).status(), 200);
    await member.screenshot({ path: resolve(output, 'account-390.png'), fullPage: true });

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
    await member.reload(); await member.waitForURL('**/login');
    await admin.screenshot({ path: resolve(output, 'members-1440.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ passed: 1, failed: 0, skipped: 0,
      scenario: 'real invitation, registration, 2FA enrollment, downloads, RBAC, immediate access revocation', syntheticData: true }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
