/* Проверка рабочего сайта: API не подменяется, данные учетной записи не нужны. */
const { createRequire } = require('node:module');
const { resolve } = require('node:path');
const { mkdirSync, existsSync } = require('node:fs');
const assert = require('node:assert/strict');
const projectRequire = createRequire(resolve(__dirname, '../frontend/package.json'));
const { chromium } = projectRequire('@playwright/test');

(async () => {
  const base = process.env.PGWEB_BROWSER_URL || 'http://127.0.0.1:5173';
  const output = resolve(process.env.PGWEB_BROWSER_ARTIFACTS || 'artifacts/browser');
  mkdirSync(output, { recursive: true });
  const executablePath = process.env.PGWEB_CHROMIUM_EXECUTABLE ||
    (existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined);
  const browser = await chromium.launch({ executablePath, headless: true, args: ['--no-sandbox'] });
  let cases = 0;
  try {
    for (const width of [320, 390, 768, 1024, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(base);
      await page.locator('#client-demo[data-ready="true"]').waitFor();
      assert.equal(await page.locator('html').getAttribute('lang'), 'en');
      assert.equal(await page.locator('#client-demo').getAttribute('data-device'), width <= 760 ? 'android' : 'windows');
      await page.evaluate(() => {
        const frame = document.querySelector('#client-demo');
        window.__browserCheck = { frame, document: frame.contentDocument, loads: 0 };
        frame.addEventListener('load', () => window.__browserCheck.loads++);
      });
      for (const language of ['en', 'ru']) {
        await page.getByRole('button', { name: language === 'en' ? 'English' : 'Русский', exact: true }).click();
        await page.locator(`#client-demo[data-language="${language}"]`).waitFor();
        await page.evaluate(() => document.fonts.ready);
        const layout = await page.evaluate(() => {
          const all = ['.hero-intro', '.hero h1', '.hero-desc', '.hero-actions .btn', '.hero-note', '.platforms', '.hero-boundary'];
          const x = all.map(selector => document.querySelector(selector).getBoundingClientRect().x);
          const intro = document.querySelector('.hero-intro').getBoundingClientRect();
          const toolbar = document.querySelector('.demo-toolbar').getBoundingClientRect();
          const controls = ['.appearance-button', '.language-switch', '.sign-in-btn'].map(selector => document.querySelector(selector).getBoundingClientRect().height);
          const label = document.querySelector('.sign-in-btn span');
          const range = document.createRange(); range.selectNodeContents(label);
          return { x, controls, lines: range.getClientRects().length, overflow: document.documentElement.scrollWidth > innerWidth,
            topDelta: intro.y + intro.height / 2 - toolbar.y - toolbar.height / 2 };
        });
        assert.equal(layout.overflow, false, `overflow ${width}/${language}`);
        assert.ok(layout.x.every(value => Math.abs(value - layout.x[0]) < 1), `left edge ${width}/${language}`);
        assert.equal(layout.lines, 1);
        assert.ok(layout.controls.every(value => Math.abs(value - 36) < 1));
        if (width > 980) assert.ok(Math.abs(layout.topDelta) < 1);
        const before = await page.locator('#client-demo').boundingBox();
        const initial = await page.locator('#client-demo').getAttribute('data-device');
        const next = initial === 'windows' ? 'android' : 'windows';
        await page.locator(`button[data-device="${next}"]`).click();
        await page.locator(`#client-demo[data-device="${next}"]`).waitFor();
        assert.deepEqual(await page.locator('#client-demo').boundingBox(), before);
        await page.locator(`button[data-device="${initial}"]`).click();
        await page.locator(`#client-demo[data-device="${initial}"]`).waitFor();
        if ([390, 1440].includes(width)) await page.screenshot({ path: resolve(output, `app-${width}-${language}.png`), fullPage: true });
        cases++;
      }
      const client = page.frameLocator('#client-demo');
      await client.locator('.pg-app [data-nav="07-diagnostics.html"]').first().click();
      await page.locator('#client-demo[data-board="07-diagnostics.html"]').waitFor();
      assert.deepEqual(await page.evaluate(() => {
        const check = window.__browserCheck;
        const frame = document.querySelector('#client-demo');
        return { sameFrame: check.frame === frame, sameDocument: check.document === frame.contentDocument, loads: check.loads };
      }), { sameFrame: true, sameDocument: true, loads: 0 });
      await page.goto(`${base}/downloads`);
      await page.waitForURL('**/login');
      await page.locator('#auth-email').waitFor();
      if ([390, 1440].includes(width)) await page.screenshot({ path: resolve(output, `login-${width}.png`), fullPage: true });
      assert.deepEqual(errors, []);
      await page.close();
    }
    console.log(JSON.stringify({ passed: cases, failed: 0, skipped: 0, screenshots: output }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
