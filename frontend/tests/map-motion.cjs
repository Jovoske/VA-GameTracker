// Two real touch rotations used to overlap our rotateend easeTo with MapLibre's
// inertia, throwing _onEaseFrame and then leaving its render queue "already running".
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const channel = process.env.PW_CHANNEL || '';
  const browser = await chromium.launch({ headless: true,
    ...(channel ? { channel } : {}), args: ['--enable-unsafe-swiftshader'] });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, reducedMotion: 'no-preference', serviceWorkers: 'block' });
    await page.addInitScript(() => localStorage.setItem('gs_token', 'map-motion-fixture'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.stack || error.message));
    const tile = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
    await page.route(/ign\.es|catastro\.meh\.es|arcgisonline/, route => route.fulfill({ contentType: 'image/png', body: tile }));
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      const data = path === '/api/auth/me' ? { id: 'me', role: 'admin' }
        : path === '/api/map/tonight' ? { conditions: { wind_deg: 0, wind_kmh: 10, wind_label: 'From the north' }, zones: [], stands: [], routes: [], safe_ground: { status: 'ok', cells: [] }, scent_range_m: 300 }
        : path === '/api/admin/version' ? { version: 'test' }
        : path === '/api/notifications' ? { unread: 0, items: [] }
        : ['/api/map/cameras', '/api/stands', '/api/sits'].includes(path) ? [] : undefined;
      if (data === undefined) return route.fulfill({ status: 404, json: { detail: 'Not Found' } });
      return route.fulfill({ json: data });
    });
    await page.goto((process.env.BASE_URL || 'http://127.0.0.1:5173') + '/map');
    try { await page.waitForFunction(() => window.__gsMap?.loaded(), null, { timeout: 12000 }); } catch (error) { console.error({ errors, page: await page.locator('body').innerText() }); throw error; }
    await page.evaluate(() => { window.mapRotations = []; window.__gsMap.on('rotate', () => window.mapRotations.push(window.__gsMap.getBearing())); });
    const touch = await page.context().newCDPSession(page);
    const box = await page.locator('.maplibregl-canvas').boundingBox();
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    const points = (angle, radius = 70) => [0, 1].map(id => ({
      id, x: cx + (id ? 1 : -1) * radius * Math.cos(angle * Math.PI / 180),
      y: cy + (id ? 1 : -1) * radius * Math.sin(angle * Math.PI / 180),
    }));
    for (let n = 0; n < 2; n++) {
      await touch.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: points(0) });
      for (const angle of [10, 20, 24, 27]) {
        await touch.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: points(angle) });
        await page.waitForTimeout(100);
      }
      await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await page.waitForTimeout(400);
      if (errors.length) break;
    }
    await page.waitForTimeout(1200);
    assert.deepEqual(errors, [], 'two-finger rotation must not lose the animation callback');
    assert.ok(await page.evaluate(() => window.mapRotations.length > 3), 'the touch input actually rotated the map');
    assert.ok(Math.abs(await page.evaluate(() => window.__gsMap.getBearing())) < 0.01,
      'small rotations still settle at north');
    const zoom = await page.evaluate(() => window.__gsMap.getZoom());
    await page.evaluate(() => window.__gsMap.zoomIn({ duration: 100 }));
    await page.waitForTimeout(400);
    assert.ok(await page.evaluate(() => window.__gsMap.getZoom()) > zoom + 0.5,
      'the map continues to respond after the overlapping gestures');
    await page.evaluate(() => window.__gsMap.easeTo({ bearing: 45, duration: 100 }));
    await page.waitForTimeout(400);
    assert.ok(Math.abs(await page.evaluate(() => window.__gsMap.getBearing()) - 45) < 0.01,
      'intentional rotation remains available');
    await page.locator('nav.tabbar').getByRole('link', { name: 'Settings', exact: true }).click();
    await page.waitForTimeout(300);
    assert.deepEqual(errors, [], 'subsequent motion and leaving the map must not crash');
    console.log('PASS: overlapping touch rotations, north snap, later zoom/rotation, and teardown.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
