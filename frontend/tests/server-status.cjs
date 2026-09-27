// Plan item 3 with a fake server: Settings says what the server's own upkeep did.
// - App version: which change runs and since when; that only tested changes go in (or
//   that every change does, before the tests are set up); changes waiting for their
//   tests; an update that didn't go in, in red, with what was put back and when it is
//   tried again; a self-update that stopped looking; and "doesn't update itself" on a
//   laptop. It never says "Up to date" from a check that didn't run (audit D-22).
// - System: the last backup (red when it failed, is older than 36 hours or never
//   happened), the weekly restore test, and the space for photos (amber getting full,
//   red full). A folded section says "Needs a look" when something in it does (H-10, H-18).
// - A member sees none of it, and the app asks the server nothing it would refuse.
// Run against Vite (BASE_URL, PW_CHANNEL; see tests/run.sh). UX_SCREENSHOTS saves pictures.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const ago = (h) => new Date(Date.now() - h * 3600e3).toISOString();
const sha = (c) => c.repeat(40);
const healthy = {
  version: '0.23.0', commit: sha('a'),
  deploy: { checked_at: ago(0.05), late: false, source: 'deploy', running: sha('a'), running_subject: 'Wind by the hour',
    running_since: ago(30), waiting_for_tests: 2, offline: false, failed: null },
};
const okStatus = {
  cameras: 4, images: 2900, detections: 1800, empty: 400, last_sync: null, suntek: null,
  disk: { free_gb: 120.4, total_gb: 500, low: false, full: false },
  backup: { at: ago(5), ok: true, last_ok_at: ago(5), late: false, target: 'D:\\GameSense-Backup', dump_mb: 412.5,
    photos_on_server: 12034, photos_in_backup: 12034, target_free_gb: 820.3, error: null },
  restore_check: { at: ago(50), ok: true, late: false, photos_checked: 50, photos_found: 50, error: null },
};

(async () => {
  // PW_CHANNEL= (empty, the default) uses Playwright's own Chromium.
  const channel = process.env.PW_CHANNEL || '';
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.env.BASE_URL || 'http://127.0.0.1:5173';
  const shots = process.env.UX_SCREENSHOTS;
  try {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      localStorage.setItem('gs_token', 'server-status-fixture');
      // Both sections open, as an owner who looked last time would have them.
      localStorage.setItem('gs.settings.open.version', '1');
      localStorage.setItem('gs.settings.open.system', '1');
    });
    const page = await context.newPage();
    const errors = [], refused = [];
    page.on('pageerror', (e) => errors.push(e.message));
    let role = 'admin', version = healthy, status = okStatus;
    await page.route('**/api/**', (route) => {
      const u = new URL(route.request().url()), path = u.pathname;
      if (path.startsWith('/api/admin/') && role !== 'admin') { refused.push(path); return route.fulfill({ status: 403, json: { detail: 'Admins only' } }); }
      const json = path === '/api/auth/me' ? { id: 'me', email: `${role}@estate.local`, role }
        : path === '/api/admin/version' ? version
        : path === '/api/admin/status' ? status
        : path === '/api/notifications/settings' ? { enabled: false, configured: false, species: [], cameras: [], quiet_start: null, quiet_end: null, plan_push: false, public_key: '', subscriptions: 0 }
        : path === '/api/notifications' ? { unread: 0, items: [] }
        : path === '/api/harvests' ? { season: 2026, label: '2026–27', from: '2026-09-01', to: '2027-08-31', seasons: [], items: [], can_export: true }
        : [];
      return route.fulfill({ json });
    });
    const section = (id) => page.locator(`#${id}`);
    const head = (id) => section(id).locator('.settings-section-head');

    // ── all well ──
    await page.goto(base + '/settings');
    const v = section('version');
    await v.getByText('Running “Wind by the hour”, live since', { exact: false }).waitFor();
    await v.getByText('Only changes that passed the tests go in. The server looks every 10 minutes (last look', { exact: false }).waitFor();
    await v.getByText('2 newer changes are waiting for their tests to pass.').waitFor();
    assert.equal(await v.getByRole('alert').count(), 0);
    assert.equal(await page.getByText(/Up to date|Check for updates/).count(), 0, 'no check that never ran');
    await v.locator('summary', { hasText: 'The detail' }).click();
    await v.getByText(`This server runs commit ${sha('a').slice(0, 7)}.`).waitFor();
    const sys = section('system');
    await sys.locator('[data-backup="ok"]').getByText('5 h ago').waitFor();
    await sys.getByText('database 412.5 MB · 12,034 photos · 820.3 GB free there').waitFor();
    await sys.locator('[data-restore="ok"]').getByText('Passed 2 d ago').waitFor();
    await sys.locator('[data-disk="ok"]').getByText('120.4 GB free', { exact: true }).waitFor();
    assert.equal(await sys.getByRole('alert').count(), 0);
    assert.equal(await head('system').getByText('Needs a look').count(), 0);
    assert.equal(await head('version').innerText().then((t) => t.includes('v0.23.0')), true);
    if (shots) { fs.mkdirSync(shots, { recursive: true }); await v.screenshot({ path: `${shots}/version-ok.png` }); await sys.screenshot({ path: `${shots}/system-ok.png` }); }

    // ── an update that didn't go in, and a backup that failed ──
    version = { ...healthy, deploy: { ...healthy.deploy, source: 'main', waiting_for_tests: null,
      failed: { commit: sha('b'), subject: 'New map sheet', step: 'health', reason: 'The new version didn’t answer as healthy within 90 seconds.',
        at: ago(0.1), attempts: 1, gave_up: false, rolled_back: true } } };
    status = { ...okStatus, disk: { free_gb: 12.3, total_gb: 500, low: true, full: false },
      backup: { ...okStatus.backup, at: ago(3), ok: false, last_ok_at: ago(27), error: 'The backup folder D:\\GameSense-Backup can’t be written.' },
      restore_check: { at: ago(3), ok: false, late: false, photos_checked: 50, photos_found: 47, error: '3 of 50 photos looked for are not in the backup’s photo folder.' } };
    await page.reload();
    const failed = v.getByRole('alert');
    await failed.getByText('An update didn’t go in: “New map sheet”. The new version didn’t answer as healthy within 90 seconds. The version before it was put back and is running. It tries again in 10 minutes.').waitFor();
    await v.getByText('Every change goes in as it is made: the tests aren’t set up to check them first yet.', { exact: false }).waitFor();
    await head('version').getByText('Needs a look').waitFor();
    await sys.locator('[data-backup="bad"]').getByRole('alert').getByText('The backup folder D:\\GameSense-Backup can’t be written. The last good one is from 1 d ago.', { exact: false }).waitFor();
    await sys.locator('[data-restore="bad"]').getByRole('alert').getByText('3 of 50 photos looked for are not in the backup’s photo folder.', { exact: false }).waitFor();
    await sys.locator('[data-disk="low"]').getByText('12.3 GB free. Getting full: free some space on the server soon.').waitFor();
    await head('system').getByText('Needs a look').waitFor();
    const amber = await sys.locator('[data-disk="low"] span').nth(1).evaluate((el) => getComputedStyle(el).color);
    const red = await sys.locator('[data-backup="bad"] span').nth(1).evaluate((el) => getComputedStyle(el).color);
    assert.notEqual(amber, red, 'getting full is amber, a failed backup red');
    if (shots) { await v.screenshot({ path: `${shots}/version-failed.png` }); await sys.screenshot({ path: `${shots}/system-bad.png` }); }

    // ── the self-update stopped; no backup ever; a full disk ──
    version = { ...healthy, deploy: { ...healthy.deploy, checked_at: ago(2), late: true, waiting_for_tests: 0 } };
    status = { ...okStatus, disk: { free_gb: 3.1, total_gb: 500, low: true, full: true }, backup: null, restore_check: null };
    await page.reload();
    await v.getByRole('alert').getByText('The server last looked for updates 2 h ago. The GameSense-Update task on the server may have stopped.').waitFor();
    await sys.locator('[data-backup="bad"]').getByText('None on record. Set up the nightly backup on the server (deploy/register-tasks.ps1).').waitFor();
    await sys.locator('[data-restore="ok"]').getByText('Not run yet.').waitFor();
    await sys.locator('[data-disk="full"]').getByText('3.1 GB free. Full: new photos aren’t fetched until some space is freed on the server.').waitFor();
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({ width, height: 844 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}px`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    for (const id of ['version', 'system']) assert.ok((await head(id).boundingBox()).height >= 44, 'glove-sized');
    if (shots) { await v.screenshot({ path: `${shots}/version-late.png` }); await sys.screenshot({ path: `${shots}/system-none.png` }); }

    // ── a laptop: no self-update ──
    version = { version: '0.23.0', commit: null, deploy: null };
    await page.reload();
    await v.getByText('This server doesn’t update itself.').waitFor();
    assert.equal(await v.getByText('The detail').count(), 0);

    // ── a member's phone: none of it, and nothing asked that would be refused ──
    role = 'member'; refused.length = 0;
    const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    await phone.addInitScript(() => localStorage.setItem('gs_token', 'server-status-member'));
    const member = await phone.newPage();
    member.on('pageerror', (e) => errors.push(e.message));
    await phone.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.startsWith('/api/admin/')) { refused.push(path); return route.fulfill({ status: 403, json: { detail: 'Admins only' } }); }
      const json = path === '/api/auth/me' ? { id: 'm', email: 'member@estate.local', role: 'member' }
        : path === '/api/notifications/settings' ? { enabled: false, configured: false, species: [], cameras: [], quiet_start: null, quiet_end: null, plan_push: false, public_key: '', subscriptions: 0 }
        : path === '/api/notifications' ? { unread: 0, items: [] }
        : path === '/api/harvests' ? { season: 2026, label: '2026–27', from: '2026-09-01', to: '2027-08-31', seasons: [], items: [], can_export: false }
        : [];
      return route.fulfill({ json });
    });
    await member.goto(base + '/settings');
    await member.locator('#password').waitFor();
    await member.waitForTimeout(500);
    assert.equal(await member.locator('#version').count(), 0);
    assert.equal(await member.locator('#system').count(), 0);
    assert.deepEqual(refused, [], 'a member is never answered 403');
    await phone.close();
    assert.deepEqual(errors, []);
    console.log('PASS: what runs and since when, tested changes only or every change, changes waiting for tests, an update put back and when it is tried again, a stopped self-update, a laptop; last backup, restore test and photo space in plain words with amber and red, "Needs a look" on folded sections; members see none of it; phone widths.');
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
