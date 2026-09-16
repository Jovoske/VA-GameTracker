// GameSense service worker.
//
// The previous version claimed to "cache the app shell so an installed PWA opens
// offline" and could not: its fetch handler only cached responses whose destination
// was 'navigate', 'image' or 'style', so no JavaScript module was ever stored. With
// no signal the app had no code to run, and API GETs fell back to caches.match('/'),
// handing HTML to resp.json() — which is why the field failure mode was
// "Couldn't load: Unexpected token '<'" rather than an honest offline state.
//
// This version:
//   * caches scripts, styles, fonts and navigations as they are fetched, so a second
//     visit has the code it needs;
//   * keeps the last good response for a small set of read-only API endpoints and
//     replays it when the network is gone, tagged so the UI can say how old it is;
//   * NEVER returns HTML for an /api/ request. If there is nothing cached it returns
//     JSON, because a parse exception is a worse failure than a clear message.
const CACHE = 'gamesense-v2'
const API_CACHE = 'gamesense-api-v2'
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png']

// Endpoints worth replaying offline: the plan and the ground it describes. Writes
// are never served from cache.
const CACHEABLE_API = ['/api/forecast/tonight', '/api/stands', '/api/sits', '/api/alerts']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE && k !== API_CACHE).map((k) => caches.delete(k))),
      )
      .then(() => self.clients.claim()),
  )
})

function isCacheableApi(url) {
  return CACHEABLE_API.some((p) => url.pathname === p || url.pathname.startsWith(p + '?'))
}

async function apiWithFallback(req) {
  const cache = await caches.open(API_CACHE)
  try {
    const res = await fetch(req)
    if (res.ok) {
      // Stamp when it was stored so the UI can show the age rather than implying
      // the plan is current.
      const body = await res.clone().text()
      cache.put(
        req,
        new Response(body, {
          status: 200,
          headers: {
            'Content-Type': 'application/json',
            'X-GameSense-Cached-At': new Date().toISOString(),
          },
        }),
      )
    }
    return res
  } catch (err) {
    const hit = await cache.match(req)
    if (hit) {
      const headers = new Headers(hit.headers)
      headers.set('X-GameSense-Stale', 'true')
      return new Response(await hit.text(), { status: 200, headers })
    }
    // Still JSON. Handing back the HTML shell here is what broke the app offline.
    return new Response(
      JSON.stringify({ detail: 'Offline, and nothing cached for this yet.', offline: true }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )
  }
}

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)

  if (url.pathname.startsWith('/api/')) {
    if (isCacheableApi(url)) e.respondWith(apiWithFallback(req))
    return // other API calls pass through untouched
  }

  e.respondWith(
    fetch(req)
      .then((res) => {
        // 'script' was the missing one. Without it an installed PWA has no code.
        const wanted = ['script', 'style', 'font', 'image'].includes(req.destination)
        if (res.ok && (req.mode === 'navigate' || wanted)) {
          const copy = res.clone()
          caches.open(CACHE).then((c) => c.put(req, copy))
        }
        return res
      })
      .catch(() =>
        caches.match(req).then((r) => r || caches.match('/index.html') || caches.match('/')),
      ),
  )
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
