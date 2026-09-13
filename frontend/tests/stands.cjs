// Run against Vite with: node tests/stands.cjs
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const assert = require('node:assert/strict')

;(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'msedge' })
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
      }
      if (request.method() === 'POST' && path === '/api/sits') {
        assert.equal(request.postDataJSON().stand_id, 'free')
        stands[0].claimed_tonight = true; stands[0].claimed_by = 'me'
        sits.push({ id: 'mine', stand_id: 'free', user_id: 'me', outcome: 'unreported', started_at: null })
        return route.fulfill({ json: { id: 'mine' } })
      }
      if (request.method() === 'PATCH' && path === '/api/sits/mine') {
        assert.equal(request.postDataJSON().outcome, 'cancelled')
        sits.find(sit => sit.id === 'mine').outcome = 'cancelled'
        stands[0].claimed_tonight = false; stands[0].claimed_by = null
        return route.fulfill({ json: {} })
      }
      unknownRoutes.push(`${request.method()} ${path}`)
      return route.fulfill({ status: 404, json: { detail: 'Not Found' } })
    })

    await page.goto(`${process.env.BASE_URL || 'http://127.0.0.1:5173'}/stands`)
    const free = page.locator('#stand-free')
    await free.getByRole('button', { name: 'Reserve for tonight' }).waitFor()
    assert.equal(await page.getByRole('alert').count(), 0, 'Valid signed-in users can load stands')
    assert.equal(await page.locator('#stand-taken').getByRole('button').count(), 0, 'Another user’s reservation cannot be edited')
    await free.getByRole('button', { name: 'Reserve for tonight' }).click()
    await free.getByRole('button', { name: 'Cancel reservation' }).click()
    await free.getByRole('button', { name: 'Reserve for tonight' }).waitFor()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

    failLoad = true
    await page.reload()
    await page.getByRole('alert').filter({ hasText: 'Temporarily unavailable' }).waitFor()
    failLoad = false
    await page.getByRole('button', { name: 'Retry loading stands' }).click()
    await free.getByRole('button', { name: 'Reserve for tonight' }).waitFor()
    assert.equal(await page.getByRole('alert').count(), 0, 'Retry recovers a failed load')

    stands.length = 0; sits.length = 0
    await page.reload()
    await page.getByRole('heading', { name: 'No stands yet' }).waitFor()
    await page.getByRole('link', { name: 'Add a stand on the map' }).waitFor()
    assert.deepEqual(unknownRoutes, [], 'All requests use existing backend endpoints')
    assert.deepEqual(errors, [])
    console.log('PASS: stands loading, reservations, ownership, retry, empty state, and mobile layout')
  } finally {
    await browser.close()
  }
})().catch(error => { console.error(error); process.exit(1) })
