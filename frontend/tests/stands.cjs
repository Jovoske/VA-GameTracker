// Stands with a fake server: reserve and cancel, another hunter's reservation, a failed
// load and its Try again, the empty page. Run against Vite (BASE_URL, PW_CHANNEL; see
// tests/run.sh): node tests/stands.cjs
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const assert = require('node:assert/strict')

;(async () => {
  // PW_CHANNEL= (empty, the default) uses Playwright's own Chromium.
  const channel = process.env.PW_CHANNEL || ''
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) })
  try {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' })
    await page.addInitScript(() => localStorage.setItem('gs_token', 'stands-fixture'))
    const errors = [], unknownRoutes = []
    page.on('pageerror', error => errors.push(error.message))
    const stands = [
      { id: 'free', name: 'Ridge overlook', claimed_tonight: false, claimed_by: null },
      { id: 'taken', name: 'Oak hollow', claimed_tonight: true, claimed_by: 'other' },
    ]
    const sits = [{ id: 'other-sit', stand_id: 'taken', user_id: 'other', outcome: 'unreported' }]
    let failLoad = false
    await page.route('**/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (request.method() === 'GET') {
        // Match the backend contract. /users/me does not exist; it previously
        // made the whole Stands page fail even when stands and sits loaded.
        if (path === '/api/auth/me') return route.fulfill({ json: { id: 'me', role: 'admin' } })
        if (path === '/api/stands') return failLoad
          ? route.fulfill({ status: 503, json: { detail: 'Temporarily unavailable' } })
          : route.fulfill({ json: stands })
        if (path === '/api/sits') return route.fulfill({ json: sits })
        // Your own sits, for the reports still to make.
        if (path === '/api/sits/mine') return route.fulfill({ json: { live: [], to_report: [] } })
        // The week's wind (feature 22) and a harvest to record (feature 23): none here.
        if (path === '/api/forecast/wind-week') return route.fulfill({ status: 503, json: { detail: 'No forecast' } })
        if (path === '/api/harvests/asks') return route.fulfill({ json: [] })
      }
      if (request.method() === 'POST' && path === '/api/sits') {
        assert.equal(request.postDataJSON().stand_id, 'free')
        stands[0].claimed_tonight = true; stands[0].claimed_by = 'me'
        sits.push({ id: 'my-sit', stand_id: 'free', user_id: 'me', outcome: 'unreported', started_at: null })
        return route.fulfill({ json: { id: 'my-sit' } })
      }
      if (request.method() === 'PATCH' && path === '/api/sits/my-sit') {
        assert.equal(request.postDataJSON().outcome, 'cancelled')
        sits.find(sit => sit.id === 'my-sit').outcome = 'cancelled'
        stands[0].claimed_tonight = false; stands[0].claimed_by = null
        return route.fulfill({ json: {} })
      }
      unknownRoutes.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 404, json: { detail: 'Not Found' } })
    })

    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:5173'}/stands`)
    const free = page.locator('#stand-free')
    await free.getByRole('button', { name: 'Reserve', exact: true }).waitFor()
    assert.equal(await page.getByRole('alert').count(), 0, 'Valid signed-in users can load stands')
    await page.locator('#stand-taken').getByText('Taken by another hunter').waitFor()
    assert.equal(await page.locator('#stand-taken').getByRole('button', { name: /Reserve|Cancel|Start sit/ }).count(), 0,
      'Another user’s reservation cannot be edited')
    await free.getByRole('button', { name: 'Reserve', exact: true }).click()
    await page.getByText('Ridge overlook is yours tonight.').waitFor()
    await free.getByRole('button', { name: 'Start sit' }).waitFor()
    await free.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByText('Reservation cancelled.').waitFor()
    await free.getByRole('button', { name: 'Reserve', exact: true }).waitFor()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

    failLoad = true
    await page.reload()
    // The copy kept from the last load stays on screen, saying it is not fresh.
    await page.getByRole('button', { name: 'Try again' }).first().waitFor()
    failLoad = false
    await page.getByRole('button', { name: 'Try again' }).first().click()
    await free.getByRole('button', { name: 'Reserve', exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.stand-fresh, [role="alert"]'))
    assert.equal(await page.getByRole('alert').count(), 0, 'Try again recovers a failed load')

    stands.length = 0; sits.length = 0
    await page.reload()
    await page.getByRole('heading', { name: 'No stands yet' }).waitFor()
    await page.getByRole('link', { name: /Add a stand on the map/ }).waitFor()
    assert.deepEqual(unknownRoutes, [], 'All requests use existing backend endpoints')
    assert.deepEqual(errors, [])
    console.log('PASS: stands loading, reservations, ownership, retry, empty state, and mobile layout')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exit(1) })
