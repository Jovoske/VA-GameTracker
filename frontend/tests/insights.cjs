// Insights with a fake server (plan item 11): only a difference that held up against the
// same nights shuffled is said as a finding; the rest is "Could be chance", "Too close to
// call" or "No difference" behind "Show the numbers"; the middle bar is never a finding;
// no percentage or confidence reaches the page; switching animals, a failed load and its
// Retry, an empty history and phone widths. Run against Vite (BASE_URL, PW_CHANNEL; see
// tests/run.sh). PLAYWRIGHT_MODULE points at an existing Playwright installation.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const driver = (key, ranges, rates, { days = [10, 10, 10], beats = false } = {}) => ({
  key, factor: key, sample_nights: days.reduce((a, b) => a + b, 0),
  // Deliberately not a percentage increase. It must never reach the UI as one.
  effect_pct: 900, confidence: 0.85, beats_chance: beats,
  buckets: ['low', 'mid', 'high'].map((label, i) => ({ label, min: ranges[i][0], max: ranges[i][1], rate: rates[i], days: days[i] })),
});
const data = {
  tested: true, shuffles: 200, nights: 30, range: ['2026-08-10', '2026-09-08'],
  scopes: [
    { key: 'all', label: 'All animals', total_nights: 30, sightings: 300, drivers: [
      // Held up against chance: the one finding for all animals.
      driver('wind', [[0, 5], [6, 12], [13, 25]], [8.2, 5.1, 3.4], { days: [10, 14, 6], beats: true }),
      // A difference that turns up in shuffled nights too: not a finding.
      driver('pressure', [[920, 932], [933, 940], [941, 955]], [3.2, 5.7, 8.1]),
      // Both extreme groups are rising: the low one must not be called falling pressure.
      driver('pressure_trend', [[1, 2], [3, 4], [5, 8]], [3.1, 4.2, 6.3]),
      // The middle bar is the tallest, and only the ends are ever compared: dark beats bright.
      driver('moon_illum', [[0, 25], [26, 65], [66, 100]], [5.5, 8.6, 3.9], { beats: true }),
    ] },
    { key: 'wild_boar', label: 'Wild boar', total_nights: 30, sightings: 220, drivers: [
      driver('wind', [[0, 5], [6, 12], [13, 25]], [2.1, 4.3, 7.6], { beats: true }),
      driver('pressure_trend', [[-8, -5], [-4, -3], [-2, -1]], [7.2, 5.1, 2.1]),
    ] },
    { key: 'red_deer', label: 'Red deer', total_nights: 30, sightings: 80, drivers: [
      driver('wind', [[0, 5], [6, 12], [13, 25]], [2, 2, 2]),
      driver('rain', [[0, 0], [0, 0], [0, 5]], [1, 3, 2]),
      driver('pressure_trend', [[-5, 0], [0, 0], [0, 5]], [1, 2, 3]),
    ] },
  ],
};
const insights = {
  outlook: [{ date: '2026-09-08', moon_phase: 'Waxing', moon_illum: 42, darkness_minutes: 600, sunset: '2026-09-08T18:30:00Z', civil_twilight_end: '2026-09-08T19:00:00Z' }],
  composition: [{ label: 'Wild boar', count: 12, visits: 12, photos: 40, top_camera: 'Oak ridge' }],
  correlations: [
    { kind: 'location', statement: 'Moon Meadow and Oak ridge recorded 80% of visits.', strength: 0.8, sample: 120 },
    // A moon summary from an older server is never shown as a finding.
    { kind: 'moon', statement: 'More visits on bright nights.', strength: 0.9, sample: 50 },
  ],
};

(async () => {
  // PW_CHANNEL= (empty, the default) uses Playwright's own Chromium.
  const channel = process.env.PW_CHANNEL || '';
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const context = await browser.newContext({ viewport: { width: 1280, height: 1000 }, serviceWorkers: 'block' });
  await context.addInitScript(() => localStorage.setItem('gs_token', 'insights-test-fixture'));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let failPatterns = false, empty = false, failSummary = false;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/insights/patterns') return route.fulfill(failPatterns ? { status: 503, json: { detail: 'Fixture unavailable' } } : { json: empty ? { scopes: [], nights: 0, tested: true } : data });
    if (path === '/api/insights') return route.fulfill(failSummary ? { status: 503, json: { detail: 'Fixture unavailable' } } : { json: insights });
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 'member', role: 'member', email: 'test@example.com' } });
    return route.fulfill({ json: [] });
  });
  const base = process.env.BASE_URL || process.env.UX_BASE_URL || 'http://127.0.0.1:5173';
  const card = title => page.getByRole('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  const weather = page.locator('.insights-weather');
  const numbers = () => weather.locator('.weather-more > summary');
  await page.goto(base + '/insights');

  // The findings: said once, in words; moon summaries of old are not among them.
  await page.getByText('Moon Meadow and Oak ridge recorded 80% of visits.', { exact: true }).first().waitFor();
  assert.equal(await page.getByText('More visits on bright nights.').count(), 0);
  // Weather: only what beat chance is a sentence, and only the two ends are compared.
  const found = weather.getByRole('list', { name: 'Weather findings for all animals' });
  await found.getByText('More animals when the wind is light than when it is windy.', { exact: true }).waitFor();
  // The moon's middle bar is the tallest, but only the ends were tested: the finding is about them.
  await found.getByText('More animals on a dark moon than on a bright moon.', { exact: true }).waitFor();
  assert.equal(await found.getByRole('listitem').count(), 2, 'the pressure, which did not beat chance, is not a finding');
  assert.equal(await found.getByText(/in between/i).count(), 0, 'the middle bar is never a finding');
  await weather.getByText('These held up when the same nights were shuffled 200 times.').waitFor();
  assert.equal(await page.getByText(/900%|90% more activity|Lower third|Higher third|confidence/i).count(), 0);
  // The numbers are behind a fold, opened from the keyboard.
  assert.equal(await weather.locator('.weather-more').getAttribute('open'), null);
  await numbers().focus(); await page.keyboard.press('Enter');
  await card('Wind').getByText('More visits when the wind is light than when it is windy', { exact: true }).waitFor();
  await card('Air pressure').getByText('Could be chance', { exact: true }).waitFor();
  await card('Moon').getByText('More visits on a dark moon than on a bright moon', { exact: true }).waitFor();
  assert.equal(await card('Moon').locator('.weather-bar-row').nth(0).locator('.is-highest').count(), 1, 'the dark-moon end is marked');
  assert.equal(await card('Moon').locator('.weather-bar-row').nth(1).locator('.is-highest').count(), 0, 'the taller middle bar is not');
  assert.equal(await card('Pressure change').getByText(/falls/).count(), 0, 'rising pressure is never called falling');
  await card('Pressure change').locator('.weather-bar-label').getByText('Bigger rises', { exact: true }).waitFor();
  assert.equal(await card('Wind').getByRole('img').getAttribute('aria-label'),
    'Wind. Visits a night per camera. Light wind: 8.2. In between: 5.1. Strong wind: 3.4');
  await card('Wind').locator('summary').click();
  await card('Wind').getByRole('cell', { name: '0–5 km/h', exact: true }).waitFor();
  await card('Temperature').getByText('Not enough nights to compare yet', { exact: true }).waitFor();
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 1000 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}px`);
  }
  if (process.env.UX_SCREENSHOTS) {
    fs.mkdirSync(process.env.UX_SCREENSHOTS, { recursive: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: process.env.UX_SCREENSHOTS + '/insights-mobile.png', fullPage: true });
    await page.setViewportSize({ width: 1280, height: 1000 });
  }

  // Another animal: its own finding, its own bars.
  await page.getByRole('button', { name: 'Wild boar', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Wild boar', exact: true }).getAttribute('aria-pressed'), 'true');
  await weather.getByText('More wild boar when it is windy than when the wind is light.', { exact: true }).waitFor();
  await numbers().click();
  await card('Pressure change').locator('.weather-bar-label').getByText('Bigger falls', { exact: true }).waitFor();
  await card('Moon').getByText('Not enough nights to compare yet', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Red deer', exact: true }).click();
  await weather.getByText('No weather or moon pattern stands out from chance for red deer yet. Keep the cameras running.').waitFor();
  await numbers().click();
  await card('Wind').getByText('No difference', { exact: true }).waitFor();
  await card('Rain').getByText('Too close to call', { exact: true }).waitFor();
  await card('Pressure change').locator('.weather-bar-label').getByText('Rises or no change', { exact: true }).waitFor();
  await card('Pressure change').locator('.weather-bar-label').getByText('Falls or no change', { exact: true }).waitFor();

  // The weather failing never takes the rest of the page with it; Retry brings it back.
  failPatterns = true;
  await page.reload();
  await weather.getByRole('alert').getByRole('button', { name: 'Retry' }).waitFor();
  await page.getByRole('heading', { name: 'Moon and last light this week' }).waitFor();
  failPatterns = false;
  await weather.getByRole('alert').getByRole('button', { name: 'Retry' }).click();
  await weather.getByText('More animals when the wind is light than when it is windy.', { exact: true }).waitFor();
  assert.equal(await weather.getByRole('alert').count(), 0);
  // No history yet: said so, no empty cards.
  empty = true;
  await page.reload();
  await page.getByText('Not enough nights on the cameras yet. Findings appear as sightings build up.').waitFor();
  assert.equal(await page.getByRole('article').count(), 0);
  // The findings failing: said so with a Retry; the weather still shows.
  empty = false; failSummary = true;
  await page.reload();
  await page.getByText(/Could not (load|refresh) the findings/).waitFor();
  await weather.getByText('More animals when the wind is light than when it is windy.', { exact: true }).waitFor();
  failSummary = false;
  await page.locator('.insights-page > .status-panel').getByRole('button', { name: 'Retry' }).click();
  await page.locator('.insights-page > .status-panel').waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('PASS: findings only when they beat chance, ends compared not the middle, no percentages, species switching, keyboard fold, phone widths, failed loads with Retry, empty history.');
})().catch(e => { console.error(e); process.exit(1); });
