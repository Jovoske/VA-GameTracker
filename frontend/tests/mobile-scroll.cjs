const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({ headless: true, channel: 'msedge' });
 try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  await page.addInitScript(() => localStorage.setItem('gs_token', 'scroll-test-fixture'));
  await page.route('**/api/**', route => route.fulfill({json: new URL(route.request().url()).pathname === '/api/cameras'
   ? Array.from({length: 12}, (_, i) => ({ id: `c${i}`, name: `Camera ${i + 1}`, image_count: 24, empty_count: 4, battery_pct: 72, signal_pct: 80, health: null })) : []}));
  await page.goto('http://127.0.0.1:5173/cameras');
  await page.getByText('Camera 12', {exact: true}).waitFor();
  await page.evaluate(() => window.scrollTo(0, 600));
  await page.waitForFunction(() => scrollY >= 600);
  const header = await page.locator('.appbar').evaluate(el => ({bottom: el.getBoundingClientRect().bottom, filter: getComputedStyle(el).filter, backdrop: getComputedStyle(el).backdropFilter}));
  console.log('Scrolled header:', header);
  assert.ok(header.bottom <= 0, 'The static brand banner must scroll out of the mobile data viewport');
  assert.equal(header.filter, 'none');
  assert.equal(header.backdrop, 'none');
  assert.ok(await page.locator('.tabbar').isVisible(), 'Mobile navigation remains available');
  console.log('PASS: mobile content replaces the brand banner on scroll; no app-header blur.');
 } finally { await browser.close(); }
})().catch(e => { console.error(e.message); process.exit(1); });
