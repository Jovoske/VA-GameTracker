// GameSense service worker.
//
// What it is for: an installed app that opens, with tonight's plan, wherever the
// hunter is. On one bar of signal, with no signal, after a deploy, or while the
// server or its tunnel is down.
//
//   * Every build stamps this file with its id and its asset list (vite.config.ts),
//     so each deploy installs a new worker, and that worker stores the whole app at
//     install: the page, every script and style, the map included. The first visit
//     after "Add to Home Screen" is therefore enough for the next one to open with
//     no signal (audit K-03). Old builds are pruned on activate, keeping the one
//     before so an app left open across a deploy can still open the map (D-20).
//   * /assets/* are content-hashed and never change: served from the store first.
//     On a weak link that is the difference between the plan in a second and a
//     black screen for a minute (D-09, J-06).
//   * Opening the app goes to the network, but waits at most 3 s when the stored
//     page can stand in, and a 5xx or Cloudflare 52x/530 counts as no signal: the
//     stored page opens instead of an error page (K-02).
//   * A script or style is never answered with index.html. That turned a missing
//     file into "Expected a JavaScript module" and a blank screen (B-02, D-01).
//   * A small set of read-only API answers is kept and replayed when the network
//     is gone or the server is down, tagged with when it was stored, so the page
//     says how old it is. An /api/ request is never answered with HTML.
const BUILD = '__GS_BUILD__'
const ASSETS = /*__GS_ASSETS__*/[]
const SHELL_PREFIX = 'gamesense-shell-'
const SHELL_CACHE = SHELL_PREFIX + BUILD
const API_CACHE = 'gamesense-api-v2'
// The one cache the worker before this one kept everything in.
const LEGACY_CACHE = 'gamesense-v2'
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png']
const NAV_WAIT_MS = 3000

// Endpoints worth replaying offline: the plan and the ground it describes. Writes
// are never served from cache.
const CACHEABLE_API = ['/api/forecast/tonight', '/api/stands', '/api/sits', '/api/alerts']

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((c) =>
        // The shell has to be whole or the worker isn't worth installing. The rest
        // is stored one by one, so one file that won't come on a thin link doesn't
        // cost all the others; anything missed is stored when it is first used.
        c.addAll(SHELL).then(() => Promise.all(ASSETS.map((u) => c.add(u).catch(() => {})))),
      )
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => {
        // Keep this build and the newest one before it: a page still running that
        // build after a deploy can open its map from here instead of a 404.
        const older = keys.filter((k) => k !== SHELL_CACHE && (k.startsWith(SHELL_PREFIX) || k === LEGACY_CACHE))
        const keepPrevious = older[older.length - 1]
        return Promise.all(
          keys
            .filter((k) => k !== SHELL_CACHE && k !== API_CACHE && k !== keepPrevious)
            .map((k) => caches.delete(k)),
        )
      })
      .then(() => self.clients.claim())
      // Every open page learns which build is stored now; one running an older
      // build offers a reload (src/serviceWorker.ts).
      .then(() => self.clients.matchAll({ type: 'window' }))
      .then((list) => list.forEach((c) => c.postMessage({ type: 'gs-sw-build', build: BUILD }))),
  )
})

// A 5xx is the server or the tunnel in front of it, not an answer: Cloudflare
// sends 502/504 for a dead origin and 52x/530 for a dead tunnel.
const serverDown = (res) => res.status >= 500 && res.status <= 599

function isCacheableApi(url) {
  return CACHEABLE_API.some((p) => url.pathname === p || url.pathname.startsWith(p + '?'))
}

async function replay(cache, req, reason) {
  const hit = await cache.match(req)
  if (!hit) return null
  const headers = new Headers(hit.headers)
  headers.set('X-GameSense-Stale', 'true')
  headers.set('X-GameSense-Stale-Reason', reason)
  return new Response(await hit.text(), { status: 200, headers })
}

async function apiWithFallback(req) {
  const cache = await caches.open(API_CACHE)
  let res
  try {
    res = await fetch(req)
  } catch (err) {
    // The page gave up on it (left the tab, or its own timeout): nothing to answer.
    if (req.signal && req.signal.aborted) throw err
    const hit = await replay(cache, req, 'offline')
    if (hit) return hit
    // Still JSON. Handing back the HTML shell here is what broke the app offline.
    return new Response(
      JSON.stringify({ detail: 'Offline, and nothing cached for this yet.', offline: true }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )
  }
  if (res.ok) {
    // Stamp when it was stored so the UI can show the age rather than implying
    // the plan is current.
    const body = await res.clone().text()
    cache.put(
      req,
      new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-GameSense-Cached-At': new Date().toISOString() },
      }),
    )
    return res
  }
  if (serverDown(res)) return (await replay(cache, req, 'server')) || res
  // 401 and the other 4xx pass through: the app signs out on a 401.
  return res
}

async function storedShell() {
  return (await caches.match('/index.html', { cacheName: SHELL_CACHE })) || (await caches.match('/index.html'))
}

async function navigate(req) {
  const stored = await storedShell()
  const network = fetch(req)
  let res
  try {
    res = stored
      ? await Promise.race([network, new Promise((resolve) => setTimeout(() => resolve(null), NAV_WAIT_MS))])
      : await network
  } catch {
    return stored || Response.error()
  }
  // Too slow: open the stored app now. The browser still checks for a newer
  // worker on its own, and that one brings the newer app with it.
  if (!res) {
    network.catch(() => {})
    return stored
  }
  if (serverDown(res) && stored) return stored
  return res
}

async function asset(req) {
  const hit = await caches.match(req)
  if (hit) return hit
  try {
    const res = await fetch(req)
    if (res.ok) {
      const copy = res.clone()
      caches.open(SHELL_CACHE).then((c) => c.put(req, copy))
    }
    // A 404 goes through as a 404: the page then reloads once for the new build.
    return res
  } catch {
    return Response.error()
  }
}

async function otherFile(req) {
  try {
    const res = await fetch(req)
    if (!serverDown(res)) return res
    return (await caches.match(req)) || res
  } catch {
    return (await caches.match(req)) || Response.error()
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  // Map tiles and anything else from another site go straight to the network.
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith('/api/')) {
    if (isCacheableApi(url)) e.respondWith(apiWithFallback(req))
    return // other API calls pass through untouched
  }
  if (req.mode === 'navigate') return e.respondWith(navigate(req))
  if (url.pathname.startsWith('/assets/')) return e.respondWith(asset(req))
  e.respondWith(otherFile(req))
})

// ── Web Push ──
// The server sends a small JSON body: { title, body, url, tag, at }. Same `tag` per
// species, so a second sounder an hour later replaces the first banner rather than
// stacking under it. Anything unparseable still shows as a plain notification —
// a push that arrived and was silently dropped is the worst outcome.
self.addEventListener('push', (e) => {
  let data = {}
  try {
    data = e.data ? e.data.json() : {}
  } catch {
    data = { title: 'GameSense', body: e.data ? e.data.text() : '' }
  }
  const title = data.title || 'GameSense'
  const opts = {
    body: data.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    data: { url: data.url || '/' },
    timestamp: data.at ? Date.parse(data.at) || Date.now() : Date.now(),
  }
  e.waitUntil(self.registration.showNotification(title, opts))
})

// Tapping the banner focuses the app if it is open and sends it to the page the
// notification points at; otherwise it opens the app there.
self.addEventListener('notificationclick', (e) => {
  e.notification.close()
  const target = new URL((e.notification.data && e.notification.data.url) || '/', self.location.origin).href
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ('focus' in client) {
          if ('navigate' in client) client.navigate(target).catch(() => {})
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
