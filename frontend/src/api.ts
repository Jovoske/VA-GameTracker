const TOKEN_KEY = 'gs_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/** Authenticated URL for a photo.
 *
 * `/api/images/{id}/file` used to be open to anyone holding the UUID. Trail cameras
 * photograph people as well as animals, so it now requires a token — and an <img>
 * tag cannot send an Authorization header, so the token rides in the query string.
 * Every photo `src` in the app must go through here or it renders as a broken image.
 */
export function imageUrl(path: string): string {
  const token = getToken()
  if (!token) return path
  return `${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
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

/**
 * `timeoutMs` gives up on a request that never answers, which on a valley
 * connection is likelier than one that fails: without it a Save button can say
 * "Saving…" forever. The error then carries `timeout: true`. A request dropped by
 * the network carries `offline: true`, and one the server refused carries `status`.
 * An abort from the caller's own `signal` is passed through untouched.
 */
export async function api<T>(path: string, options: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
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
      throw e
    }
  }

  try {
    const resp = await guard(() => fetch(`/api${path}`, { ...init, headers, signal: ctl?.signal ?? outer }))

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
      const detail = await resp.json().catch(() => ({}))
      // The status rides along so a caller can say something specific about a 409.
      throw Object.assign(new Error(detail.detail || `Something went wrong (${resp.status})`), { status: resp.status })
    }
    // DELETEs answer 204 with no body — resp.json() on that rejects and the caller
    // never gets to refresh, which reads as "the button did nothing".
    if (resp.status === 204) return undefined as T
    return await guard(() => resp.json() as Promise<T>)
  } finally {
    window.clearTimeout(timer)
  }
}

/** Last-good copy of a GET response, so the plan survives a dead valley.
 *
 * The service worker replays cached API responses, but only for an installed PWA
 * that already has the worker running. This is the belt to that braces: a plain
 * localStorage copy the page can paint from immediately, before any network call
 * resolves, with the age attached so the UI never implies it is current.
 */
const PLAN_KEY = 'gs_cache:'

export type Cached<T> = { data: T; at: string }

export function readCache<T>(path: string): Cached<T> | null {
  try {
    const raw = localStorage.getItem(PLAN_KEY + path)
    return raw ? (JSON.parse(raw) as Cached<T>) : null
  } catch {
    return null
  }
}

function writeCache(path: string, data: unknown): void {
  try {
    localStorage.setItem(PLAN_KEY + path, JSON.stringify({ data, at: new Date().toISOString() }))
  } catch {
    // Quota or private mode — caching is an optimisation, never a hard dependency.
  }
}

/** GET that caches on success and falls back to the last good copy offline. */
export async function apiCached<T>(path: string): Promise<Cached<T>> {
  try {
    const data = await api<T>(path)
    writeCache(path, data)
    return { data, at: new Date().toISOString() }
  } catch (e) {
    const hit = readCache<T>(path)
    if (hit) return hit
    throw e
  }
}

export function ageLabel(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs} h ago`
  return `${Math.round(hrs / 24)} d ago`
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

/** Who is signed in, asked once per sign-in (and again after a failure or an hour).
 *
 * The photo viewer opens from six places and each needs to know whether this person
 * may mark a photo; one shared answer saves six calls on a weak signal. */
export function whoAmI(): Promise<Me> {
  const token = getToken()
  if (meCache && meCache.token === token && Date.now() - meCache.at < 3_600_000) return meCache.p
  const p = api<Me>('/auth/me', { timeoutMs: 20_000 })
  const entry = { token, at: Date.now(), p }
  meCache = entry
  p.catch(() => { if (meCache === entry) meCache = null })
  return p
}

export async function login(email: string, password: string): Promise<void> {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(data.access_token)
}
