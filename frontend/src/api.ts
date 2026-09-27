const TOKEN_KEY = 'gs_token'
const ME_KEY = 'gs_me'
const PASS_KEY = 'gs_img'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ME_KEY)
    setImagePass(null)
  }
}

/**
 * The same person's sign-in, renewed by the server (X-Session-Token): a sign-in a
 * week old is swapped for a fresh one as it is used, so a hunter using the app
 * daily is never sent to the sign-in page at the 30-day mark (audit D-11). Who is
 * signed in stays known under the new token, so nothing on screen changes.
 */
function renewToken(next: string): void {
  const old = getToken()
  if (!old || old === next) return
  try {
    localStorage.setItem(TOKEN_KEY, next)
    const saved = JSON.parse(localStorage.getItem(ME_KEY) || 'null')
    if (saved && saved.token === old) localStorage.setItem(ME_KEY, JSON.stringify({ ...saved, token: next }))
  } catch {
    // Storage blocked: the old sign-in keeps working until it runs out.
  }
  if (meKnown?.token === old) meKnown = { ...meKnown, token: next }
  if (meCache?.token === old) meCache = { ...meCache, token: next }
}

/** Who the stored token belongs to (its `sub`), without asking the server. */
export function tokenSubject(): string | null {
  try {
    const part = getToken()?.split('.')[1]
    if (!part) return null
    const sub = (JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))) as { sub?: unknown }).sub
    return typeof sub === 'string' ? sub : null
  } catch {
    return null
  }
}

/** The service worker's stores of photos (THUMB_CACHE, PHOTO_CACHE in public/sw.js),
 *  kept by address without the photo pass. */
export const PHOTO_CACHES = ['gamesense-thumbs-v1', 'gamesense-photos-v1']

/** Sit reports waiting for signal. Written by sits.ts; named here so sign-out can clear it. */
export const SIT_QUEUE_KEY = 'gs_sit_queue'

/**
 * Sign out, and take this person's unsent sit reports and saved sits with them.
 *
 * A phone gets passed round a hunting party. Left behind, the next person to sign
 * in would find the last one's sits on screen, and an admin's login would be
 * allowed to send the last one's reports as their own. An expired sign-in (a 401)
 * keeps them: that is the same hunter signing in again.
 */
export function signOut(): void {
  setToken(null)
  meCache = null
  meKnown = null
  for (const path of [...memory.keys()]) if (path.startsWith('/sits')) memory.delete(path)
  try {
    localStorage.removeItem(SIT_QUEUE_KEY)
    for (const key of Object.keys(localStorage)) if (key.startsWith(SAVED + '/sits')) localStorage.removeItem(key)
  } catch {
    // Blocked storage: nothing was saved there either.
  }
  if ('caches' in window) {
    caches.open(WORKER_API_CACHE)
      .then(async (c) => Promise.all((await c.keys()).filter((r) => new URL(r.url).pathname.startsWith('/api/sits')).map((r) => c.delete(r))))
      .catch(() => {})
    // The photos this phone kept open without a pass; the next person signs in for theirs.
    PHOTO_CACHES.forEach((name) => { caches.delete(name).catch(() => {}) })
  }
}

/**
 * The photo pass: what a photo's address carries so an <img> can open it.
 *
 * An <img> tag can't send the sign-in header, so the address has to hold something.
 * It used to hold the 30-day sign-in itself, which then sat in server logs and in
 * any copied photo link as a working login to the whole app (audit C-19, D-08,
 * H-13). The pass opens photos and nothing else, for hours. The server sends it on
 * every answer (X-Image-Token) and with the sign-in, the same text all through a
 * 6-hour window so photo addresses, and what the phone keeps of them, hold still.
 */
let pass: string | null = null
try { pass = localStorage.getItem(PASS_KEY) } catch { /* private mode: kept in memory */ }

export function setImagePass(next: string | null): void {
  if (next === pass) return
  pass = next
  try {
    if (next) localStorage.setItem(PASS_KEY, next)
    else localStorage.removeItem(PASS_KEY)
  } catch {
    // Storage blocked: it lives in memory for this session.
  }
}

/** When a token stops working (its `exp`), in ms; 0 when it can't be read. */
function expiresAt(token: string | null): number {
  try {
    const part = token?.split('.')[1]
    const exp = part ? (JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))) as { exp?: unknown }).exp : null
    return typeof exp === 'number' ? exp * 1000 : 0
  } catch {
    return 0
  }
}

/** The pass the phone has, if it has a few minutes left in it. */
function livePass(): string | null {
  return pass && expiresAt(pass) > Date.now() + 5 * 60_000 ? pass : null
}

let passAsked: Promise<string | null> | null = null

/** Ask for a new pass (once, however many photos want one), or null with no answer. */
export function freshPass(): Promise<string | null> {
  if (!getToken()) return Promise.resolve(null)
  if (!passAsked) {
    passAsked = api<{ image_token: string }>('/auth/image-token', { timeoutMs: 15_000 })
      .then((r) => { setImagePass(r.image_token); return r.image_token })
      .catch(() => null)
      .finally(() => { window.setTimeout(() => { passAsked = null }, 10_000) })
  }
  return passAsked
}

/** A photo's address, with the photo pass on it.
 *
 * Every photo `src` in the app goes through here (and thumbUrl). With no pass yet,
 * or one about to run out, a new one is asked for and the address goes without:
 * the photo that fails for it is loaded again once the pass comes
 * (installPhotoRetry). Never the sign-in itself.
 */
export function imageUrl(path: string): string {
  const p = livePass()
  if (!p) {
    if (getToken()) void freshPass()
    return path
  }
  return `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(p)}`
}

const PHOTO_PATH = /^\/api\/images\/[^/]+\/(thumb|file)$/

/**
 * A photo that didn't load for want of a pass (none yet, or it ran out while the
 * app sat in a pocket) is loaded again with a new one, once. Its page never sees
 * that first failure. A photo that fails with a good pass (gone from the server,
 * no signal) fails as before, and the page says so.
 */
export function installPhotoRetry(): void {
  document.addEventListener('error', (e) => {
    const img = e.target
    if (!(img instanceof HTMLImageElement) || !getToken()) return
    let url: URL
    try { url = new URL(img.currentSrc || img.src, location.href) } catch { return }
    if (url.origin !== location.origin || !PHOTO_PATH.test(url.pathname)) return
    const tried = url.searchParams.get('token')
    const have = livePass()
    if ((tried && tried === have) || img.dataset.gsRetried === url.pathname) return
    img.dataset.gsRetried = url.pathname
    e.stopPropagation()
    void (have ? Promise.resolve(have) : freshPass()).then((next) => {
      if (next && next !== tried) {
        url.searchParams.set('token', next)
        img.src = url.pathname + url.search
      } else {
        img.dispatchEvent(new Event('error'))
      }
    })
  }, true)
}

/** A photo's small copy, for every grid, strip and the map.
 *
 * A 320px-wide WebP the server makes once and the phone keeps for a year, so a
 * page of tiles costs a few hundred KB instead of a page of originals on a weak
 * signal. The photo viewer still opens `file_url`, the full photo.
 */
export function thumbUrl(imageId: string): string {
  return imageUrl(`/api/images/${imageId}/thumb`)
}

/** What a hunter reads instead of the browser's own "Failed to fetch" or "Load failed". */
export const NO_SIGNAL = 'No signal. Try again when you have a connection.'
export const NO_ANSWER = 'No answer from the server.'
export const SERVER_DOWN = 'The server isn’t answering. Try again in a minute.'

/** How long a page waits for a GET before it goes with what the phone has saved. */
export const GET_TIMEOUT_MS = 15_000

type Options = RequestInit & { timeoutMs?: number }
export type Failure = Error & { status?: number; offline?: boolean; timeout?: boolean }

/**
 * `timeoutMs` gives up on a request that never answers, which on a valley
 * connection is likelier than one that fails: without it a Save button can say
 * "Saving…" forever. The error then carries `timeout: true`. A request dropped by
 * the network carries `offline: true`, and one the server refused carries `status`.
 * An abort from the caller's own `signal` is passed through untouched.
 */
async function request<T>(path: string, options: Options = {}): Promise<{ data: T; headers: Headers }> {
  const { timeoutMs, ...init } = options
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const outer = init.signal
  const ctl = timeoutMs ? new AbortController() : null
  let timedOut = false
  let timer = 0
  if (ctl) {
    if (outer?.aborted) ctl.abort(outer.reason)
    else outer?.addEventListener('abort', () => ctl.abort(outer.reason), { once: true })
    timer = window.setTimeout(() => { timedOut = true; ctl.abort() }, timeoutMs)
  }
  // The body is read inside the same guard: a connection can stall halfway through it.
  const guard = async <R,>(work: () => Promise<R>): Promise<R> => {
    try { return await work() } catch (e) {
      if (timedOut) throw Object.assign(new Error(NO_ANSWER), { timeout: true })
      if ((e as Error).name === 'AbortError' || outer?.aborted) throw e
      // fetch reports a dropped connection as a bare TypeError; anything else is real.
      if (e instanceof TypeError) throw Object.assign(new Error(NO_SIGNAL), { offline: true })
      // A 200 that isn't JSON is a page from something in the way (a hotspot's
      // sign-in page, an old app shell), not an answer.
      if (e instanceof SyntaxError) throw new Error('The server’s answer didn’t make sense. Reload the app.')
      throw e
    }
  }

  try {
    const resp = await guard(() => fetch(`/api${path}`, { ...init, headers, signal: ctl?.signal ?? outer }))
    // The photo pass and a renewed sign-in ride on every answer (backend deps.py).
    if (token && resp.ok) {
      const img = resp.headers.get('X-Image-Token')
      if (img) setImagePass(img)
      const renewed = resp.headers.get('X-Session-Token')
      if (renewed && getToken() === token) renewToken(renewed)
    }

    // An expired or revoked session is not a data-loading failure — showing it as one
    // leaves the user staring at a red error with no way forward. Clear the dead token
    // and send them to sign in. Only when we actually sent a token: a 401 without one is
    // a failed login attempt, which the login form reports itself.
    if (resp.status === 401 && token) {
      setToken(null)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.assign('/login?expired=1')
      }
      throw new Error('You were signed out. Sign in again.')
    }

    if (!resp.ok) {
      const body = await guard(() => resp.json()).catch(() => ({}))
      // The service worker's "nothing saved for this yet" is no signal, not a server fault.
      if (body?.offline) throw Object.assign(new Error(NO_SIGNAL), { offline: true, status: resp.status })
      throw Object.assign(new Error(detailText(body?.detail, resp.status)), { status: resp.status })
    }
    // DELETEs answer 204 with no body — resp.json() on that rejects and the caller
    // never gets to refresh, which reads as "the button did nothing".
    if (resp.status === 204) return { data: undefined as T, headers: resp.headers }
    return { data: await guard(() => resp.json() as Promise<T>), headers: resp.headers }
  } finally {
    window.clearTimeout(timer)
  }
}

/** A refusal in words. FastAPI's 422 carries a list, which used to read "[object Object]";
 *  a dead server or tunnel carries an HTML page, which is no use to anyone. */
function detailText(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const first = detail.find((d) => d && typeof d.msg === 'string')
    if (first) return `That wasn’t accepted: ${String(first.msg).replace(/^Value error, /, '')}`
  }
  if (status >= 500) return SERVER_DOWN
  // The status rides along so a caller can say something specific about a 409.
  return `Something went wrong (${status})`
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  return (await request<T>(path, options)).data
}

/** Why a saved copy is on screen instead of a fresh answer. */
export type StaleWhy = 'offline' | 'timeout' | 'server'

/** No signal, no answer, or the server (or its tunnel) down: the cases a saved copy is for.
 *  A refusal (4xx) is an answer, and the caller's own abort is not a failure at all. */
export function noAnswer(e: unknown): StaleWhy | null {
  const x = e as Failure
  if (x?.offline) return 'offline'
  if (x?.timeout) return 'timeout'
  if (x?.status && x.status >= 500) return 'server'
  return null
}

/** The first words of a line about a saved copy: "No signal." */
export function noAnswerWords(why: StaleWhy | null | undefined): string {
  return why === 'server' ? 'Can’t reach the server.' : why === 'timeout' ? 'No answer from the server.' : 'No signal.'
}

/**
 * A GET's answer, when it was true, and whether it is a saved copy.
 *
 * `at` is when the answer was fetched, never when it was read back: a plan saved
 * at 16:00 and shown at 22:00 with no signal says "from 6 h ago", not "just now".
 */
export type Got<T> = { data: T; at: string; stale: boolean; why?: StaleWhy }

/**
 * The last good answers, two ways.
 *
 * In memory, for this session: flicking Tonight → Stands → Tonight paints what was
 * there a moment ago instead of starting over from "Loading…" (audit K-08). And in
 * localStorage for the few a page needs with no signal at all, after the phone was
 * off (the plan, the stands, the chips). The service worker keeps its own copies
 * too, for an installed app; this is the belt to those braces.
 */
const SAVED = 'gs_cache:'
const MEMORY_MAX = 40
const memory = new Map<string, Got<unknown>>()

function remember(path: string, got: Got<unknown>): void {
  memory.delete(path)
  memory.set(path, got)
  if (memory.size > MEMORY_MAX) memory.delete(memory.keys().next().value as string)
}

function readSaved<T>(path: string): Got<T> | null {
  try {
    const raw = localStorage.getItem(SAVED + path)
    if (!raw) return null
    const v = JSON.parse(raw) as { data: T; at: string }
    return v && typeof v.at === 'string' ? { data: v.data, at: v.at, stale: false } : null
  } catch {
    return null
  }
}

function writeSaved(path: string, got: Got<unknown>): void {
  try {
    localStorage.setItem(SAVED + path, JSON.stringify({ data: got.data, at: got.at }))
  } catch {
    // Quota or private mode — saving is an optimisation, never a hard dependency.
  }
}

const newer = <T,>(a: Got<T> | null, b: Got<T> | null) =>
  !a ? b : !b ? a : Date.parse(b.at) > Date.parse(a.at) ? b : a

/** The service worker's store of API answers (API_CACHE in public/sw.js). */
const WORKER_API_CACHE = 'gamesense-api-v2'
/** What "Download the estate" saved (src/map/offline.ts, ESTATE_CACHE in public/sw.js):
 *  the camera sheets, the likely paths and the estate's box among the rest. */
export const ESTATE_CACHE = 'gamesense-estate-v1'

/** Which saved answers each page read, so a page that breaks drops only its own. */
const readOn = new Map<string, Set<string>>()
function noteRead(path: string): void {
  const page = location.pathname
  let paths = readOn.get(page)
  if (!paths) readOn.set(page, (paths = new Set()))
  paths.add(path)
}

/**
 * Throw away the saved answers the page at `page` read: one of them may be what
 * broke it, and a page that crashes on its saved copy would otherwise crash again
 * before it could ask for a new one. Called when a page breaks (ErrorBoundary).
 * Only that page's: a bug on Photos must not cost the plan saved for tonight.
 * The service worker's copy goes too, or it would hand the same answer back.
 */
export function forgetSaved(page: string = location.pathname): void {
  const paths = [...(readOn.get(page) ?? [])]
  readOn.delete(page)
  if (!paths.length) return
  paths.forEach((p) => memory.delete(p))
  try {
    paths.forEach((p) => localStorage.removeItem(SAVED + p))
  } catch {
    // Storage blocked: nothing was saved there either.
  }
  if ('caches' in window) {
    for (const name of [WORKER_API_CACHE, ESTATE_CACHE]) {
      caches.open(name)
        .then((c) => Promise.all(paths.map((p) => c.delete(`/api${p}`))))
        .catch(() => {})
    }
  }
}

/** The newest answer the phone already has for `path`, to paint before asking again. */
export function peek<T>(path: string): Got<T> | null {
  noteRead(path)
  const got = newer(memory.get(path) as Got<T> | undefined ?? null, readSaved<T>(path))
  return got && { ...got, stale: false, why: undefined }
}

/**
 * The service worker's own copies, read by the page: its store of answers and the
 * estate saved on the phone. The worker only answers from them when the network
 * fails outright; on a link that hangs, the page gives up first (its timeout) and
 * the worker never gets the chance (audit J-06, review R4FE-4). A page with nothing
 * saved of its own then still has something to show.
 */
async function workerCopy<T>(path: string): Promise<Got<T> | null> {
  let best: Got<T> | null = null
  if (!('caches' in window)) return best
  for (const cacheName of [WORKER_API_CACHE, ESTATE_CACHE]) {
    try {
      const hit = await caches.match(`/api${path}`, { cacheName })
      const at = hit?.headers.get('X-GameSense-Cached-At')
      if (hit && at) best = newer(best, { data: (await hit.json()) as T, at, stale: true })
    } catch {
      // A copy that won't read is no copy.
    }
  }
  return best
}

/**
 * The newest copy the phone has for `path`, wherever it keeps one (this session,
 * its own store, the service worker's, the estate saved on it), for a sheet to paint
 * at once while it asks again. Null when there is none.
 */
export async function savedCopy<T>(path: string): Promise<Got<T> | null> {
  const got = newer(peek<T>(path), await workerCopy<T>(path))
  return got && { ...got, stale: true }
}

/**
 * GET with a timeout that falls back to the last good copy.
 *
 * A fresh answer is remembered (and, with `save`, kept on the phone). When there is
 * no answer, or the service worker answers with its own saved copy (it says so in
 * X-GameSense-Stale), the newest copy the phone has comes back marked `stale`, with
 * the time it was really fetched. Only when there is no copy at all does it throw.
 */
export async function getFresh<T>(
  path: string,
  opts: { signal?: AbortSignal; timeoutMs?: number; save?: boolean } = {},
): Promise<Got<T>> {
  noteRead(path)
  try {
    const { data, headers } = await request<T>(path, { signal: opts.signal, timeoutMs: opts.timeoutMs ?? GET_TIMEOUT_MS })
    if (headers.get('X-GameSense-Stale')) {
      const why: StaleWhy = headers.get('X-GameSense-Stale-Reason') === 'server' ? 'server' : 'offline'
      // When it was stored; failing that, when the server says it made it (the plan does).
      const made = (data as { generated_at?: unknown } | null)?.generated_at
      const at = headers.get('X-GameSense-Cached-At') || (typeof made === 'string' ? made : new Date(0).toISOString())
      const replayed: Got<T> = { data, at, stale: true, why }
      const mine = peek<T>(path)
      return { ...(newer(replayed, mine) as Got<T>), stale: true, why }
    }
    const got: Got<T> = { data, at: new Date().toISOString(), stale: false }
    remember(path, got)
    if (opts.save) writeSaved(path, got)
    return got
  } catch (e) {
    const why = noAnswer(e)
    if (!why) throw e
    const mine = newer(peek<T>(path), await workerCopy<T>(path))
    if (mine) return { ...mine, stale: true, why }
    throw e
  }
}

export { fromEarlierNight, nightBefore, nightOf } from './night'

export function ageLabel(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  return `${Math.round(hrs / 24)} d ago`
}

/** A server's reason without its technical detail: "The animal detector could not
 * start (ModuleNotFoundError: …)." reads "The animal detector could not start." The
 * detail, in brackets (nested ones too), belongs behind a fold. */
export function plainWords(text: string): string {
  let t = text
  for (let before = ''; before !== t;) {
    before = t
    t = t.replace(/\s*\([^()]*\)/g, '')
  }
  return t.replace(/\s+([.,;:])/g, '$1').trim()
}

/** "21:40" today, "Tue 21:40" this week, "4 Sep 21:40" before that. */
export function whenLabel(iso: string): string {
  const d = new Date(iso)
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  const days = (Date.now() - d.getTime()) / 86_400_000
  if (d.toDateString() === new Date().toDateString()) return time
  if (days < 6) return `${d.toLocaleDateString(undefined, { weekday: 'short' })} ${time}`
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${time}`
}

export type Me = { id: string; email: string; role: 'admin' | 'member' | 'viewer' }
let meCache: { token: string | null; at: number; p: Promise<Me> } | null = null
let meKnown: { token: string | null; me: Me } | null = null

/** Who is signed in, asked once per sign-in (and again after a failure or an hour).
 *
 * The photo viewer opens from six places and each needs to know whether this person
 * may mark a photo; one shared answer saves six calls on a weak signal. The answer is
 * also kept on the phone for this sign-in, so Stands still knows which reservation
 * is yours with no signal (audit A-18). */
export function whoAmI(): Promise<Me> {
  const token = getToken()
  if (meCache && meCache.token === token && Date.now() - meCache.at < 3_600_000) return meCache.p
  const entry = { token, at: Date.now(), p: null as unknown as Promise<Me> }
  entry.p = api<Me>('/auth/me', { timeoutMs: 20_000 }).then(
    (me) => {
      meKnown = { token, me }
      try { localStorage.setItem(ME_KEY, JSON.stringify({ token, me })) } catch { /* private mode */ }
      return me
    },
    (e) => {
      if (meCache === entry) meCache = null
      const saved = savedMe(token)
      if (saved && noAnswer(e)) return saved
      throw e
    },
  )
  meCache = entry
  return entry.p
}

/** Who is signed in, as far as the phone already knows, without asking: the page
 *  paints "Yours tonight" at once instead of after /auth/me answers, which on one
 *  bar can be the full 20 s. whoAmI() then confirms or corrects it. */
export function peekMe(): Me | null {
  const token = getToken()
  return meKnown && meKnown.token === token ? meKnown.me : savedMe(token)
}

function savedMe(token: string | null): Me | null {
  try {
    const v = JSON.parse(localStorage.getItem(ME_KEY) || 'null')
    return v && token && v.token === token ? (v.me as Me) : null
  } catch {
    return null
  }
}

/** Who signed in last on this phone, to fill the sign-in form (never a guess). */
export const LAST_EMAIL_KEY = 'gs_last_email'

/** This phone's known-phone mark from its last sign-in. It opens nothing; sent with
 *  the next sign-in, it keeps a crowd of strangers guessing the same email from
 *  holding this phone up (backend api/throttle.py). Kept through sign-out: it
 *  belongs to the phone, not to the sign-in. */
export const PHONE_KEY = 'gs_phone'

export async function login(email: string, password: string): Promise<void> {
  let phone: string | null = null
  try { phone = localStorage.getItem(PHONE_KEY) } catch { /* private mode */ }
  const data = await api<{ access_token: string; image_token?: string | null; known_phone?: string | null }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password, known_phone: phone }),
  })
  setToken(data.access_token)
  setImagePass(data.image_token ?? null)
  try {
    localStorage.setItem(LAST_EMAIL_KEY, email.trim())
    if (data.known_phone) localStorage.setItem(PHONE_KEY, data.known_phone)
  } catch { /* private mode */ }
}

/** A password change: this phone gets a new sign-in and pass in the answer; every
 *  other phone signed in as this person is signed out (backend routes_auth). */
export async function changePassword(current: string, next: string): Promise<string> {
  const r = await api<{ access_token: string; image_token: string; note: string }>('/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: current, new_password: next }),
  })
  renewToken(r.access_token)
  setImagePass(r.image_token)
  return r.note
}
