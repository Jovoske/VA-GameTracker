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
//     no signal (audit K-03). The page and the files it names must all arrive or
//     the new worker doesn't take over; the map and the fonts are best effort. Old
//     builds are pruned on activate, keeping the one before so an app left open
//     across a deploy can still open the map (D-20).
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
//   * Photos are kept by their address without the photo pass (?token=), which
//     changes every few hours (audit C-19): a photo never changes, so one seen
//     yesterday opens from the phone today, pass or no pass, signal or none. The
//     newest few hundred small copies and few dozen full photos are kept; signing
//     out clears them (src/api.ts). A download (?download=1) always asks the server.
//   * "Download the estate" (src/map/offline.ts) keeps the estate's map pictures,
//     the likely paths and each camera's sheet (its photo strip, marked photos and
//     small photos) in ESTATE_CACHE. Saved map pictures and small photos are served
//     from there first: they don't change, and the valley has no signal. The rest is
//     asked of the network first, kept fresh while there is signal, and replayed
//     when there isn't (audit B-06, feature 24).
const BUILD = '__GS_BUILD__'
const ASSETS = /*__GS_ASSETS__*/[]
const SHELL_PREFIX = 'gamesense-shell-'
const SHELL_CACHE = SHELL_PREFIX + BUILD
const API_CACHE = 'gamesense-api-v2'
// What "Download the estate" saved. Never pruned on activate: a deploy must not
// cost a hunter the map they saved for the valley.
const ESTATE_CACHE = 'gamesense-estate-v1'
// The base maps a phone may keep a copy of: IGN's public WMTS (PNOA aerial, MTN
// topo), free to reuse with credit. Esri's terms don't allow offline copies of its
// imagery, and Catastro's parcels are asked for as they are needed.
const SAVED_TILES = ['https://www.ign.es/wmts/']
// Same-site answers a saved estate may hold: the camera sheets (photo strip, marked
// photos), the likely paths, the estate's box, and small photos.
const SAVED_API = ['/api/photos', '/api/photos/highlights', '/api/map/paths', '/api/estate']
const THUMB = /^\/api\/images\/[^/]+\/thumb$/
const PHOTO = /^\/api\/images\/[^/]+\/file$/
// Photos opened on this phone, by address without the pass; the newest kept.
const THUMB_CACHE = 'gamesense-thumbs-v1'
const PHOTO_CACHE = 'gamesense-photos-v1'
const KEEP = { [THUMB_CACHE]: 800, [PHOTO_CACHE]: 60 }
// The one cache the worker before this one kept everything in.
const LEGACY_CACHE = 'gamesense-v2'
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png']
const NAV_WAIT_MS = 3000

// Endpoints worth replaying offline: the plan and the ground it describes. Writes
// are never served from cache.
const CACHEABLE_API = ['/api/forecast/tonight', '/api/stands', '/api/sits', '/api/alerts', '/api/map/tonight', '/api/map/cameras']

self.addEventListener('install', (e) => {
  e.waitUntil(storeBuild().then(() => self.skipWaiting()))
})

// The app's own files that the stored page names: its script, its styles and any
// chunk it preloads. Read from the stored index.html itself, so they always match it.
const namedBy = (html) => [...new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]))]

async function storeBuild() {
  const c = await caches.open(SHELL_CACHE)
  let entry
  try {
    // The page and the files it can't open without have to be whole, or this worker
    // isn't worth installing: one that took over with an index.html naming a script
    // it never stored would open on nothing with no signal, where the worker before
    // it could open (a deploy, then a weak signal while the phone picked it up).
    // Failing here keeps that worker in charge, and the browser tries this build
    // again on its next update check.
    await c.addAll(SHELL)
    const page = await c.match('/index.html')
    entry = namedBy(page ? await page.text() : '')
    await c.addAll(entry)
  } catch (err) {
    await caches.delete(SHELL_CACHE)
    throw err
  }
  // The rest (the map, the fonts) one by one, so one file that won't come on a thin
  // link doesn't cost all the others; anything missed is stored when it is first used.
  await Promise.all(ASSETS.filter((u) => !entry.includes(u)).map((u) => c.add(u).catch(() => {})))
}

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
            .filter((k) => k !== SHELL_CACHE && k !== API_CACHE && k !== ESTATE_CACHE && !(k in KEEP) && k !== keepPrevious)
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

// ── the estate saved on this phone ──

/** A saved map picture first (it doesn't change), the network for the rest. A
 *  download asking again (cache: 'reload') goes to the network. */
async function savedTile(req) {
  if (req.cache !== 'reload' && req.cache !== 'no-store') {
    const hit = await caches.match(req.url, { cacheName: ESTATE_CACHE })
    if (hit) return hit
  }
  return fetch(req)
}

/** A photo, or its small copy: the copy on the phone first (a photo never changes),
 *  looked up without the photo pass, which changes; else the network, keeping what
 *  comes for next time. A refusal (an old pass) is passed on, never kept: the page
 *  asks for a new pass and loads it again. */
async function savedPhoto(req, url) {
  const key = url.origin + url.pathname
  const name = THUMB.test(url.pathname) ? THUMB_CACHE : PHOTO_CACHE
  const hit = (name === THUMB_CACHE && (await caches.match(key, { cacheName: ESTATE_CACHE, ignoreSearch: true })))
    || (await caches.match(key, { cacheName: name }))
  if (hit) return hit
  const res = await fetch(req)
  // Only a photo the server says never changes; a stand-in (a small copy it couldn't
  // make) is asked for again next time.
  if (res.ok && (res.headers.get('Cache-Control') || '').includes('immutable')) {
    const copy = res.clone()
    caches.open(name).then((c) => c.put(key, copy)).then(() => trim(name)).catch(() => {})
  }
  return res
}

// Checked every so many new photos, not on each: listing a big cache costs.
const trimEvery = { [THUMB_CACHE]: 0, [PHOTO_CACHE]: 0 }
async function trim(name) {
  if (++trimEvery[name] % 20 !== 1) return
  const c = await caches.open(name)
  const keys = await c.keys()
  // Oldest first, as they were put: those go.
  await Promise.all(keys.slice(0, Math.max(0, keys.length - KEEP[name])).map((k) => c.delete(k)))
}

/** The network first. An answer the estate keeps is kept fresh while there is
 *  signal, and replayed, marked stale, when there isn't or the server is down. */
async function savedApi(req) {
  const cache = await caches.open(ESTATE_CACHE)
  let res
  try {
    res = await fetch(req)
  } catch (err) {
    if (req.signal && req.signal.aborted) throw err
    const hit = await replay(cache, req, 'offline')
    if (hit) return hit
    return new Response(
      JSON.stringify({ detail: 'Offline, and nothing cached for this yet.', offline: true }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )
  }
  if (res.ok) {
    if (await cache.match(req)) {
      const body = await res.clone().text()
      cache.put(req, new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'X-GameSense-Cached-At': new Date().toISOString() },
      }))
    }
    return res
  }
  if (serverDown(res)) return (await replay(cache, req, 'server')) || res
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
  // Anything else from another site goes straight to the network; IGN's map
  // pictures come from the saved estate when they are in it.
  if (url.origin !== self.location.origin) {
    if (SAVED_TILES.some((p) => req.url.startsWith(p))) e.respondWith(savedTile(req))
    return
  }

  if (url.pathname.startsWith('/api/')) {
    if (isCacheableApi(url)) e.respondWith(apiWithFallback(req))
    else if ((THUMB.test(url.pathname) || PHOTO.test(url.pathname)) && !url.searchParams.has('download')) e.respondWith(savedPhoto(req, url))
    else if (SAVED_API.includes(url.pathname)) e.respondWith(savedApi(req))
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
