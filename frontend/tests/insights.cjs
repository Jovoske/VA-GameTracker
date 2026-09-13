// Run against Vite; use PLAYWRIGHT_MODULE to point at an existing installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const driver = (key, ranges, rates, days = [10, 10, 10]) => ({
  key, factor: key, sample_nights: days.reduce((a, b) => a + b, 0),
  // Deliberately not a percentage increase. It must never reach the UI as one.
  effect_pct: 900, confidence: 0.85,
  buckets: ['low', 'mid', 'high'].map((label, i) => ({ label, min: ranges[i][0], max: ranges[i][1], rate: rates[i], days: days[i] })),
});
const data = {
  scopes: [
    { key: 'all', label: 'All animals', total_nights: 30, sightings: 300, drivers: [
      driver('wind', [[0, 5], [6, 12], [13, 25]], [8.2, 5.1, 3.4], [10, 14, 6]),
      driver('pressure', [[920, 932], [933, 940], [941, 955]], [3.2, 5.7, 8.1]),
      // Both extreme groups are rising: low must not be called falling pressure.
      driver('pressure_trend', [[1, 2], [3, 4], [5, 8]], [3.1, 4.2, 6.3]),
      driver('moon_illum', [[0, 25], [26, 65], [66, 100]], [5.5, 8.6, 3.9]),
    ] },
    { key: 'wild_boar', label: 'Wild boar', total_nights: 30, sightings: 220, drivers: [
      driver('wind', [[0, 5], [6, 12], [13, 25]], [2.1, 4.3, 7.6]),
      driver('pressure_trend', [[-8, -5], [-4, -3], [-2, -1]], [7.2, 5.1, 2.1]),
    ] },
    { key: 'red_deer', label: 'Red deer', total_nights: 30, sightings: 80, drivers: [
      driver('wind', [[0, 5], [6, 12], [13, 25]], [2, 2, 2]),
      driver('rain', [[0, 0], [0, 0], [1, 5]], [1, 3, 2]),
      driver('pressure_trend', [[-5, 0], [0, 0], [0, 5]], [1, 2, 3]),
    ] },
  ], nights: 30, range: ['2026-08-10', '2026-09-08'],
};
const insights = {
  outlook: Array.from({ length: 7 }, (_, i) => ({ date: `2026-09-${String(13 + i).padStart(2, '0')}`, moon_phase: 'waxing_crescent', moon_illum: 15 + i * 10, civil_twilight_end: '2026-09-13T18:45:00Z' })),
  composition: [{ label: 'Wild boar', count: 220, top_camera: 'Oak ridge' }],
  correlations: [{ kind: 'time', statement: 'The cameras recorded the most sightings between 18:00 and 21:00.', strength: 0.5, sample: 300 },
    { kind: 'location', statement: 'Moon Meadow and Oak ridge recorded 80% of sightings.', strength: 0.8, sample: 300 },
    // A rolling deploy can briefly serve the legacy endpoint. Do not repeat its
    // incompatible moon claim alongside the new comparison.
    { statement: '~90% more activity on dark nights (<25% moon) than bright ones.', strength: 0.9, sample: 100 }],
};

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.env.BROWSER_CHANNEL || 'msedge' });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' });
  await context.addInitScript(() => localStorage.setItem('gs_token', 'insights-test-fixture'));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let failPatterns = false, empty = false, failSummary = false;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/insights/patterns') return route.fulfill(failPatterns ? { status: 503, json: { detail: 'Fixture unavailable' } } : { json: empty ? { scopes: [], nights: 0 } : data });
    if (path === '/api/insights') return route.fulfill(failSummary ? { status: 503, json: { detail: 'Fixture unavailable' } } : { json: insights });
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 'member', role: 'member', email: 'test@example.com' } });
    return route.fulfill({ json: [] });
  });
  const base = process.env.UX_BASE_URL || 'http://127.0.0.1:5173';
  const card = title => page.getByRole('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await page.goto(base + '/insights');
  await card('Wind').getByText('Most sightings: lighter wind', { exact: true }).waitFor();
  assert.equal(await page.getByText(/900%|90% more activity|Lower third|Higher third|confidence/i).count(), 0);
  await card('Pressure changes').getByText('Most sightings: bigger rises', { exact: true }).waitFor();
  assert.equal(await card('Pressure changes').getByText(/falls/).count(), 0);
  await card('Moon').getByText('Most sightings: in between', { exact: true }).waitFor();
  await page.getByText('Moon Meadow and Oak ridge recorded 80% of sightings.', { exact: true }).waitFor();
  assert.equal(await card('Wind').locator('details').getAttribute('open'), null);
  const details = card('Wind').locator('summary');
  await details.focus(); await page.keyboard.press('Enter');
  await card('Wind').getByRole('cell', { name: '0–5 km/h', exact: true }).waitFor();
  assert.equal(await card('Wind').getByRole('img').getAttribute('aria-label'), 'Wind. Average camera sightings per day. Lighter wind: 8.2. In between: 5.1. Stronger wind: 3.4');
  await details.click();
  await page.getByRole('heading', { name: 'When do cameras see more animals?' }).click();
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}px`);
  }
  if (process.env.UX_SCREENSHOTS) {
    fs.mkdirSync(process.env.UX_SCREENSHOTS, { recursive: true });
    await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/insights-desktop.png', fullPage: true });
    await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/insights-preview.png' });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/insights-mobile.png', fullPage: true });
  }
  await page.getByRole('button', { name: 'Wild boar', exact: true }).click();
  await card('Wind').getByText('Most sightings: stronger wind', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Wild boar', exact: true }).getAttribute('aria-pressed'), 'true');
  await card('Pressure changes').getByText('Most sightings: bigger falls', { exact: true }).waitFor();
  await card('Moon').getByText('No comparison available yet', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Red deer', exact: true }).click();
  await card('Wind').getByText('No single condition stands out', { exact: true }).waitFor();
  await card('Pressure changes').locator('.weather-bar-label').getByText('Rises or no change', { exact: true }).waitFor();
  await card('Pressure changes').locator('.weather-bar-label').getByText('Falls or no change', { exact: true }).waitFor();
  await page.locator('.weather-more > summary').click();
  await card('Rain').getByText('These conditions overlap too much to pick a winner', { exact: true }).waitFor();
  failPatterns = true;
  await page.reload();
  await page.getByRole('button', { name: 'Retry comparisons' }).waitFor();
  await page.getByRole('heading', { name: 'Moon & last light this week' }).waitFor();
  assert.equal(await page.getByText('No comparison available yet', { exact: true }).count(), 0);
  failPatterns = false;
  await page.getByRole('button', { name: 'Retry comparisons' }).click();
  await card('Wind').getByText('Most sightings: lighter wind', { exact: true }).waitFor();
  empty = true;
  await page.reload();
  await page.getByText('There is not enough history to compare animal groups yet.', { exact: false }).waitFor();
  assert.equal(await page.getByText('No comparison available yet', { exact: true }).count(), 8);
  empty = false; failSummary = true;
  await page.reload();
  await card('Wind').getByText('Most sightings: lighter wind', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Retry loading insights' }).waitFor();
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('PASS: visual averages, truthful labels, species switching, middle peak, ties, overlapping conditions, disclosure keyboard access, mobile widths, error/retry, empty history, and independently loading weather comparisons.');
})().catch(e => { console.error(e); process.exit(1); });
