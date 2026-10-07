// Replay a browser translator replacing text nodes while Tonight refreshes its plan.
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const channel = process.env.PW_CHANNEL || '';
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
    await page.addInitScript(() => localStorage.setItem('gs_token', 'tonight-dom-fixture'));
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      const data = path === '/api/auth/me' ? { id: 'me', role: 'member' }
        : path === '/api/forecast/tonight' ? {
          verdict: 'QUIET', recommended: null, conditions: {}, where: [], alternates: [], alerts: [],
          nights_of_data: 20, exposure: { note: new URL(route.request().url()).searchParams.has('species') ? null : 'Two unchecked nights excluded.' },
        }
        : path === '/api/species' ? [{ id: 'red_deer', common_name: 'Red Deer', huntable: true, hidden: false, detections: 10 }]
        : path === '/api/notifications' ? { unread: 0, items: [] }
        : ['/api/sits', '/api/alerts', '/api/stands'].includes(path) ? [] : undefined;
      if (data === undefined) return route.fulfill({ status: 404, json: { detail: 'Not Found' } });
      return route.fulfill({ json: data });
    });
    await page.goto((process.env.BASE_URL || 'http://127.0.0.1:5173') + '/');
    await page.getByText('Two unchecked nights excluded.', { exact: false }).waitFor();
    await page.evaluate(() => {
      const root = document.querySelector('.tn-foot');
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) if (walker.currentNode.textContent.trim()) nodes.push(walker.currentNode);
      for (const node of nodes) {
        const replacement = document.createElement('font');
        replacement.textContent = node.textContent;
        node.replaceWith(replacement);
      }
    });
    await Promise.all([
      page.waitForResponse(response => response.url().includes('/forecast/tonight?')),
      page.locator('.tn-chips button').nth(1).click(),
    ]);
    await page.waitForTimeout(100);
    assert.deepEqual(errors, [], 'a translated footnote must not crash React removeChild when refreshed');
    assert.equal(await page.getByText('Something broke.', { exact: true }).count(), 0);
    assert.equal(await page.locator('.tn-foot').count(), 1);
    assert.equal(await page.locator('.tn-foot').getByText('Two unchecked nights excluded.', { exact: false }).count(), 0);
    console.log('PASS: Tonight survives translated text being replaced during a plan refresh.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
