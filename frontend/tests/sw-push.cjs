// The service worker's push side (plan item 15), without a browser: sw.js is loaded
// with a stand-in `self` (registration.showNotification, pushManager.subscribe,
// clients), fed pushes and a pushsubscriptionchange, and what it does is checked.
//
//   * A buzz carries renotify (and is not silent); a quiet update of the same banner
//     carries neither: same tag, renotify false, silent true (audit K-06).
//   * renotify needs a tag; the link and the photo's time ride along.
//   * Anything unparseable still shows, as a plain notification.
//   * pushsubscriptionchange subscribes again with the old options when the browser
//     gave no new subscription, and asks every open page to send it (gs-push-changed,
//     src/push.ts listenForNewSubscriptions), since the worker can't sign in (D-04).
//
// Run: node frontend/tests/sw-push.cjs (no stack needed).
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')

const src = fs.readFileSync(path.join(__dirname, '..', 'public', 'sw.js'), 'utf8')
// Objects made inside the worker's context have its own prototypes: compared as data.
const plain = (x) => JSON.parse(JSON.stringify(x))

function load({ subscribeFails = false } = {}) {
  const on = {}
  const shown = []
  const subscribed = []
  const posted = []
  const self = {
    addEventListener: (type, fn) => { on[type] = fn },
    location: { origin: 'https://gamesense.example' },
    registration: {
      showNotification: async (title, opts) => { shown.push({ title, opts }) },
      pushManager: {
        subscribe: async (options) => {
          subscribed.push(options)
          if (subscribeFails) throw new Error('AbortError: push service unreachable')
          return { endpoint: 'https://push.example/new' }
        },
      },
    },
    clients: {
      matchAll: async (q) => {
        assert.deepEqual(plain(q), { type: 'window', includeUncontrolled: true }, 'every open page, controlled or not')
        return [{ postMessage: (m) => posted.push(m) }, { postMessage: (m) => posted.push(m) }]
      },
    },
    skipWaiting: () => {},
  }
  vm.runInNewContext(src, { self, URL, console, setTimeout, clearTimeout, caches: {}, fetch: () => {} })
  return { on, shown, subscribed, posted }
}

async function fire(sw, type, event) {
  let wait = Promise.resolve()
  sw.on[type]({ ...event, waitUntil: (p) => { wait = p } })
  await wait
}

const pushed = (payload) => ({
  data: typeof payload === 'string'
    ? { json: () => JSON.parse(payload), text: () => payload }
    : { json: () => payload, text: () => JSON.stringify(payload) },
})

;(async () => {
  const sw = load()
  for (const type of ['push', 'notificationclick', 'pushsubscriptionchange']) {
    assert.equal(typeof sw.on[type], 'function', `sw.js listens for ${type}`)
  }

  // ── the buzz, then a quiet update of the same banner ──
  const at = '2026-09-15T22:55:00.000Z'
  await fire(sw, 'push', pushed({
    title: 'Wild boar at PL19', body: '1 visit at 00:53.', url: '/photos?species=wild_boar&image=a&at=x',
    tag: 'sighting-wild_boar', renotify: true, silent: false, at,
  }))
  await fire(sw, 'push', pushed({
    title: 'Wild boar at PL19', body: '2 visits since 00:53, last one 01:08.', url: '/photos?species=wild_boar&image=b',
    tag: 'sighting-wild_boar', renotify: false, silent: true, at,
  }))
  const [buzz, update] = sw.shown
  assert.equal(buzz.title, 'Wild boar at PL19')
  assert.equal(buzz.opts.body, '1 visit at 00:53.')
  assert.equal(buzz.opts.tag, 'sighting-wild_boar')
  assert.equal(buzz.opts.renotify, true, 'the first in the cooldown buzzes')
  assert.equal(buzz.opts.silent, false)
  assert.equal(buzz.opts.data.url, '/photos?species=wild_boar&image=a&at=x', 'the tap opens the photo')
  assert.equal(buzz.opts.timestamp, Date.parse(at), 'stamped with when it happened')
  assert.equal(update.opts.tag, 'sighting-wild_boar', 'the same banner')
  assert.equal(update.opts.renotify, false, 'a quiet update does not buzz again')
  assert.equal(update.opts.silent, true)
  assert.equal(update.opts.body, '2 visits since 00:53, last one 01:08.')

  // renotify without a tag is not a thing: every banner is new anyway.
  await fire(sw, 'push', pushed({ title: 'Test alert', body: 'x', renotify: true }))
  assert.equal(sw.shown[2].opts.renotify, false)
  assert.equal(sw.shown[2].opts.tag, undefined)
  assert.equal(sw.shown[2].opts.data.url, '/')
  // Anything unparseable still shows.
  await fire(sw, 'push', pushed('not json'))
  assert.equal(sw.shown[3].title, 'GameSense')
  assert.equal(sw.shown[3].opts.body, 'not json')
  assert.equal(sw.shown[3].opts.silent, false)

  // ── the browser replaced the subscription and gave no new one ──
  const options = { userVisibleOnly: true, applicationServerKey: new Uint8Array([4, 1, 2]).buffer }
  await fire(sw, 'pushsubscriptionchange', { oldSubscription: { options }, newSubscription: null })
  assert.deepEqual(sw.subscribed, [options], 'subscribes again with the same options')
  assert.deepEqual(plain(sw.posted), [{ type: 'gs-push-changed' }, { type: 'gs-push-changed' }], 'every open page is asked to send it')

  // It gave a new one: nothing to subscribe, the pages still send it.
  const again = load()
  await fire(again, 'pushsubscriptionchange', { oldSubscription: { options }, newSubscription: { endpoint: 'https://push.example/2' } })
  assert.deepEqual(again.subscribed, [])
  assert.equal(again.posted.length, 2)
  // A subscribe that fails (no signal) still tells the pages: the app subscribes
  // itself when it sends its subscription (checkThisDevice).
  const broken = load({ subscribeFails: true })
  await fire(broken, 'pushsubscriptionchange', { oldSubscription: { options }, newSubscription: null })
  assert.equal(broken.subscribed.length, 1)
  assert.equal(broken.posted.length, 2)

  console.log('sw-push: ok')
})().catch((e) => { console.error(e); process.exit(1) })
