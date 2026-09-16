// Provider controls with mocked accounts; no real camera credentials or cloud requests.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge' });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' });
    await page.addInitScript(() => localStorage.setItem('gs_token', 'ubox-settings-test-fixture'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const accounts = [{
      id: 'ubox-1', label: 'Oak ridge UBox', username: 'owner@example.test', provider: 'ubox',
      owner: 'owner@example.test', active: true, cameras: 2, can_remove: true, can_edit: true,
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500,
      last_import: { at: '2026-09-16T10:00:00Z', downloaded: 12, interval_skipped: 36, daily_limit_skipped: 4, no_image: 2, failed: 0 },
    }, {
      id: 'spypoint-1', label: 'Field SPYPOINT', username: 'guest@example.test', provider: 'spypoint',
      owner: 'guest@example.test', active: true, cameras: 1, can_remove: false, can_edit: false,
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500, last_import: null,
    }];
    let posted = null;
    let patched = null;
    await page.route('**/api/**', async route => {
      const { pathname } = new URL(route.request().url());
      if (pathname === '/api/camera-accounts' && route.request().method() === 'POST') {
        posted = route.request().postDataJSON();
        return route.fulfill({ json: { note: 'Connected — UBox Pro reports 2 camera(s).' } });
      }
      if (pathname === '/api/camera-accounts/ubox-1/import-settings') {
        patched = route.request().postDataJSON();
        Object.assign(accounts[0], patched);
        return route.fulfill({ json: { note: 'Import limits saved. They apply on the next sync; existing photos stay.' } });
      }
      const data = pathname === '/api/camera-accounts' ? accounts
        : pathname === '/api/auth/me' ? { id: 'user-1', email: 'owner@example.test', role: 'member' }
        : pathname === '/api/admin/version' ? { version: 'test' }
        : pathname === '/api/admin/status' ? { cameras: 3, images: 12, detections: 8, empty: 4, last_sync: null }
        : pathname === '/api/species' ? [{ id: 'fox', common_name: 'Fox', huntable: false, detections: 8 }]
        : pathname === '/api/notifications/settings' ? { enabled: false, configured: false, species: [], public_key: '', subscriptions: 0 }
        : pathname === '/api/notifications' ? { unread: 0, items: [] }
        : [];
      return route.fulfill({ json: data });
    });
    await page.goto((process.env.UX_BASE_URL || 'http://127.0.0.1:5173') + '/settings');
    await page.getByText('Oak ridge UBox', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Camera provider').inputValue(), 'spypoint');
    assert.equal(await page.getByRole('button', { name: 'Edit import limits for Field SPYPOINT' }).count(), 0);
    await page.getByLabel('Camera provider').selectOption('ubox');
    assert.equal(await page.locator('#new-account-interval').inputValue(), '60');
    assert.equal(await page.locator('#new-account-daily').inputValue(), '500');
    await page.getByLabel('UBox Pro email', { exact: true }).fill('new@example.test');
    await page.getByLabel('UBox Pro password', { exact: true }).fill('local-test-password');
    await page.locator('#new-account-interval').fill('9');
    await page.getByRole('button', { name: 'Connect account', exact: true }).click();
    assert.equal(posted, null, 'Native validation blocks an out-of-range minimum gap');
    await page.locator('#new-account-interval').fill('60');

    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}`);
    }
    if (process.env.UX_SCREENSHOTS) {
      fs.mkdirSync(process.env.UX_SCREENSHOTS, { recursive: true });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/ubox-settings-desktop.png', fullPage: true });
      await page.setViewportSize({ width: 390, height: 1000 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/ubox-settings-mobile.png', fullPage: true });
    }
    await page.getByRole('button', { name: 'Connect account', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Connected' }).waitFor();
    assert.deepEqual(posted, {
      username: 'new@example.test', password: 'local-test-password', label: null, provider: 'ubox',
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500,
    });
    await page.getByRole('button', { name: 'Edit import limits for Oak ridge UBox' }).click();
    await page.locator('#account-ubox-1-interval').fill('120');
    await page.locator('#account-ubox-1-daily').fill('250');
    await page.getByRole('button', { name: 'Save limits', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Import limits saved' }).waitFor();
    assert.deepEqual(patched, { ubox_min_interval_seconds: 120, ubox_max_images_per_day: 250 });
    await page.getByText('Per camera: at least 120s apart, up to 250 photos/day.', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: provider default/selection, UBox Pro defaults/ranges, connect payload, editable saved limits, per-account skip counts, and 320/390/768/1280px overflow checks.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
