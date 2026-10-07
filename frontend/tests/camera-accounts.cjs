// Camera logins in Settings, with mocked accounts: no real camera credentials or cloud
// requests. Provider choice, Nordic Gamekeeper login, UBox Pro photo limits and their ranges, the connect call,
// editing a login's limits, the last fetch's counts, and phone widths. Run against Vite
// (BASE_URL, PW_CHANNEL; see tests/run.sh).
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  // PW_CHANNEL= (empty, the default) uses Playwright's own Chromium.
  const channel = process.env.PW_CHANNEL || '';
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' });
    await page.addInitScript(() => localStorage.setItem('gs_token', 'ubox-settings-test-fixture'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const working = { state: 'ok', error: null, last_ok_at: new Date(Date.now() - 20 * 60e3).toISOString(), cameras_failing: 0, password_problem: false };
    const accounts = [{
      id: 'ubox-1', label: 'Oak ridge UBox', username: 'owner@example.test', provider: 'ubox',
      owner: 'owner@example.test', active: true, primary: false, importing: false, status: working,
      cameras: 2, can_remove: true, can_edit: true,
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500,
      last_import: { at: '2026-09-16T10:00:00Z', status: 'ok', error: null, downloaded: 12, interval_skipped: 36, daily_limit_skipped: 4, no_image: 2, failed: 0 },
    }, {
      id: 'spypoint-1', label: 'Field SPYPOINT', username: 'guest@example.test', provider: 'spypoint',
      owner: 'guest@example.test', active: true, primary: false, importing: false, status: working,
      cameras: 1, can_remove: false, can_edit: false,
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500, last_import: null,
    }, {
      id: 'nordic-1', label: 'North clearing APEX', username: 'owner@example.test', provider: 'nordic',
      owner: 'owner@example.test', active: true, primary: false, importing: false, status: working,
      cameras: 1, can_remove: true, can_edit: true,
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500, last_import: null,
    }];
    let posted = null;
    let role = 'member';
    let rejected = false;
    let failRefresh = false;
    let posts = 0;
    let releasePost = null;
    let gatePost = false;
    let patched = null;
    await page.route('**/api/**', async route => {
      const { pathname } = new URL(route.request().url());
      if (pathname === '/api/camera-accounts' && route.request().method() === 'POST') {
        posts++;
        posted = route.request().postDataJSON();
        if (gatePost) await new Promise(resolve => { releasePost = resolve; });
        if (rejected) return route.fulfill({ status: 400, json: { detail: 'The mailbox refused the login.' } });
        const provider = posted.provider === 'nordic' ? 'Nordic Gamekeeper' : 'UBox Pro';
        return route.fulfill({ json: { note: `Connected — ${provider} reports 2 camera(s).` } });
      }
      if (pathname === '/api/camera-accounts/ubox-1/import-settings') {
        patched = route.request().postDataJSON();
        Object.assign(accounts[0], patched);
        return route.fulfill({ json: { note: 'Import limits saved. They apply on the next sync; existing photos stay.' } });
      }
      if (pathname === '/api/camera-accounts' && failRefresh) {
        failRefresh = false;
        return route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } });
      }
      const data = pathname === '/api/camera-accounts' ? accounts
        : pathname === '/api/auth/me' ? { id: 'user-1', email: 'owner@example.test', role }
        : pathname === '/api/admin/version' ? { version: 'test', commit: null, deploy: null }
        : pathname === '/api/admin/status' ? { cameras: 3, images: 12, detections: 8, empty: 4, last_sync: null }
        : pathname === '/api/species' ? [{ id: 'fox', common_name: 'Fox', huntable: false, detections: 8 }]
        : pathname === '/api/notifications/settings' ? { enabled: false, configured: false, species: [], cameras: [], quiet_start: null, quiet_end: null, plan_push: false, public_key: '', subscriptions: 0 }
        : pathname === '/api/notifications' ? { unread: 0, items: [] }
        // The harvest book (feature 23): an empty season.
        : pathname === '/api/harvests' ? { season: 2026, label: '2026–27', from: '2026-09-01', to: '2027-08-31', seasons: [{ season: 2026, label: '2026–27' }], items: [], can_export: false }
        : [];
      return route.fulfill({ json: data });
    });
    await page.goto((process.env.BASE_URL || process.env.UX_BASE_URL || 'http://127.0.0.1:5173') + '/settings');
    // Settings is folded: the logins are one row until opened.
    await page.getByRole('button', { name: /Camera logins/ }).click();
    const logins = page.locator('#accounts');
    await logins.getByText('Oak ridge UBox', { exact: true }).waitFor();
    await logins.getByText('Last fetch (', { exact: false }).getByText(/12 photos added, 36 skipped \(too close together\), 4 skipped \(daily limit\)\. 2 had no photo\./).waitFor();
    assert.equal(await page.getByLabel('Brand or protocol').inputValue(), '');
    assert.equal(await page.getByRole('button', { name: 'Edit photo limits for Field SPYPOINT' }).count(), 0, 'not yours to edit');
    const nordicLogin = logins.locator('[data-login="nordic-1"]');
    await nordicLogin.getByText('Nordic Gamekeeper', { exact: true }).waitFor();
    assert.equal(await nordicLogin.getByRole('button', { name: /Edit photo limits/ }).count(), 0, 'Nordic has no UBox import limits');
    assert.equal(await nordicLogin.getByText(/Per camera:/).count(), 0, 'Nordic has no UBox limit summary');
    await page.getByLabel('Brand or protocol').selectOption('ubox');
    assert.equal(await page.locator('#new-account-interval').inputValue(), '60');
    assert.equal(await page.locator('#new-account-daily').inputValue(), '500');
    await page.getByLabel('UBox Pro email', { exact: true }).fill('new@example.test');
    await page.getByLabel('UBox Pro password', { exact: true }).fill('local-test-password');
    await page.locator('#new-account-interval').fill('9');
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    assert.equal(posted, null, 'Native validation blocks an out-of-range minimum gap');
    await page.locator('#new-account-interval').fill('60');

    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}`);
    }
    if (process.env.UX_SCREENSHOTS) {
      fs.mkdirSync(process.env.UX_SCREENSHOTS, { recursive: true });
      await page.setViewportSize({ width: 390, height: 1000 });
      await logins.screenshot({ path: process.env.UX_SCREENSHOTS + '/ubox-settings-mobile.png' });
      await page.setViewportSize({ width: 1280, height: 1000 });
    }
    for (const b of await logins.locator('button').all()) {
      if (await b.isVisible()) assert.ok((await b.boundingBox()).height >= 44, 'glove-sized')
    }
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    await logins.getByRole('status').filter({ hasText: 'Connected' }).waitFor();
    assert.deepEqual(posted, {
      username: 'new@example.test', password: 'local-test-password', label: null, provider: 'ubox',
      ubox_min_interval_seconds: 60, ubox_max_images_per_day: 500,
    });
    await page.getByRole('button', { name: 'Edit photo limits for Oak ridge UBox' }).click();
    await page.locator('#account-ubox-1-interval').fill('120');
    await page.locator('#account-ubox-1-daily').fill('250');
    await page.getByRole('button', { name: 'Save limits', exact: true }).click();
    await logins.getByRole('status').filter({ hasText: 'Import limits saved' }).waitFor();
    assert.deepEqual(patched, { ubox_min_interval_seconds: 120, ubox_max_images_per_day: 250 });
    await page.getByText('Per camera: at least 120s apart, up to 250 photos/day.', { exact: true }).waitFor();
    await page.getByLabel('Brand or protocol').selectOption('nordic');
    assert.equal(await page.locator('#new-account-interval').count(), 0, 'Nordic connect form has no UBox limits');
    assert.equal(await page.locator('#new-account-daily').count(), 0);
    await page.getByLabel('Nordic Gamekeeper email', { exact: true }).fill('nordic@example.test');
    await page.getByLabel('Nordic Gamekeeper password', { exact: true }).fill('local-nordic-password');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Nordic overflow at ${width}`);
    }
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    await logins.getByRole('status').filter({ hasText: 'Connected — Nordic Gamekeeper' }).waitFor();
    assert.deepEqual(posted, {
      username: 'nordic@example.test', password: 'local-nordic-password', label: null, provider: 'nordic',
    });
    // Custom receiver connections are admin-only; changing providers clears secrets.
    assert.equal(await page.locator('#camera-provider option[value="suntek_email"]').count(), 0);
    role = 'admin';
    await page.reload();
    await page.locator('#camera-provider').waitFor();
    assert.equal(await page.locator('#camera-email').count(), 0);
    await page.locator('#camera-provider').selectOption('nordic');
    await page.locator('#camera-password').fill('must-not-carry-over');
    await page.locator('#camera-provider').selectOption('suntek_email');
    assert.equal(await page.locator('#camera-password').inputValue(), '');
    assert.equal(await page.locator('#camera-folder').inputValue(), 'INBOX');
    assert.equal(await page.locator('#camera-port').inputValue(), '993');
    assert.equal(await page.locator('#camera-transport').count(), 0);
    await page.locator('#camera-host').fill('imap.example.test');
    await page.locator('#camera-email').fill('inbox@example.test');
    await page.locator('#camera-password').fill('test-app-password');
    await page.locator('#camera-sender').fill('camera@example.test');
    const before = posts;
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    assert.equal(posts, before, 'camera name is required for an inbox');
    await page.locator('#camera-label').fill('Suntek clearing');
    rejected = true;
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    await logins.getByRole('status').filter({ hasText: 'refused' }).waitFor();
    assert.equal(await page.locator('#camera-host').inputValue(), 'imap.example.test');
    assert.equal(await page.locator('#camera-email').inputValue(), 'inbox@example.test');
    rejected = false;
    gatePost = true;
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#camera-provider').disabled);
    assert.equal(await page.locator('#camera-password').isDisabled(), true);
    // Even a programmatic second submit cannot dispatch another request.
    await page.getByRole('form', { name: 'Add cameras' }).evaluate(form => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await page.waitForTimeout(100);
    assert.equal(posts, before + 2);
    assert.ok(releasePost);
    failRefresh = true;
    releasePost();
    gatePost = false;
    await logins.getByRole('status').filter({ hasText: 'do not add it again' }).waitFor();
    assert.equal(await page.locator('#camera-provider').inputValue(), '');
    assert.equal(await page.locator('#camera-password').count(), 0);
    assert.deepEqual(posted, {
      provider: 'suntek_email', username: 'inbox@example.test', password: 'test-app-password', label: 'Suntek clearing',
      connection: { host: 'imap.example.test', port: 993, folder: 'INBOX', transport: 'imap_tls', sender: 'camera@example.test', timezone: 'Europe/Helsinki' },
    });
    await page.locator('#camera-provider').selectOption('suntek_ftp');
    assert.equal(await page.locator('#camera-sender').count(), 0);
    assert.equal(await page.locator('#camera-transport').inputValue(), 'ftps');
    await page.locator('#camera-host').fill('ftp.example.test');
    await page.locator('#camera-folder').fill('/clearing');
    await page.locator('#camera-email').fill('camera-user');
    await page.locator('#camera-password').fill('ftp-test-password');
    await page.locator('#camera-label').fill('Suntek FTP');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `Inbox overflow at ${width}`);
      if (process.env.UX_SCREENSHOTS && [390, 1280].includes(width)) {
        await page.setViewportSize({ width, height: 1400 });
        await page.getByRole('form', { name: 'Add cameras' }).scrollIntoViewIfNeeded();
        await page.getByRole('form', { name: 'Add cameras' }).screenshot({ path: process.env.UX_SCREENSHOTS + `/camera-setup-${width}.png` });
      }
    }
    await page.locator('#camera-transport').selectOption('ftp');
    await page.getByText('FTP sends credentials and photos without encryption. Use FTPS when supported.').waitFor();
    await page.getByRole('button', { name: 'Check and connect', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#camera-provider').value === '');
    assert.deepEqual(posted, {
      provider: 'suntek_ftp', username: 'camera-user', password: 'ftp-test-password', label: 'Suntek FTP',
      connection: { host: 'ftp.example.test', port: 21, folder: '/clearing', transport: 'ftp', sender: '', timezone: 'Europe/Helsinki' },
    });
    role = 'viewer';
    await page.reload();
    await logins.getByText('Oak ridge UBox', { exact: true }).waitFor();
    assert.equal(await page.locator('#camera-provider').count(), 0, 'viewers cannot add cameras');
    assert.deepEqual(errors, []);
    console.log('PASS: five camera connection payloads, dynamic fields, credential clearing, required fields, rejected logins, duplicate submits, refresh recovery, role restrictions, saved UBox limits and 320/390/768/1280px layouts.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
