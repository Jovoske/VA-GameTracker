const TOKEN_KEY = 'gs_token'
const ME_KEY = 'gs_me'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(ME_KEY)
  }
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

/** Throw every saved answer away: one of them may be what broke the page, and a
 *  page that crashes on its saved copy would otherwise crash before it could ask
 *  for a new one. Called when a page breaks (ErrorBoundary). */
export function forgetSaved(): void {
  memory.clear()
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i)
      if (k?.startsWith(SAVED)) localStorage.removeItem(k)
    }
  } catch {
    // Storage blocked: nothing was saved there either.
  }
}

/** The newest answer the phone already has for `path`, to paint before asking again. */
export function peek<T>(path: string): Got<T> | null {
  const got = newer(memory.get(path) as Got<T> | undefined ?? null, readSaved<T>(path))
  return got && { ...got, stale: false, why: undefined }
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
    const mine = why ? peek<T>(path) : null
    if (mine) return { ...mine, stale: true, why: why! }
    throw e
  }
}

/**
 * The night a moment belongs to, as the server counts them: the estate's own clock,
 * with anything before 06:00 still part of the evening before. "2026-10-03" is the
 * night of 3 to 4 October. A plan or a reservation from another night is not
 * tonight's, however recent it looks.
 */
const ESTATE_TZ = 'Europe/Madrid'
const estateClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: ESTATE_TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})
export function nightOf(when: string | number | Date): string {
  const p = Object.fromEntries(estateClock.formatToParts(new Date(when)).map((x) => [x.type, x.value]))
  // Six hours back on the wall clock (not the UTC one), as the server does.
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) - 6 * 3600e3
  return new Date(wall).toISOString().slice(0, 10)
}

/** Made before this morning's 06:00: it belongs to an earlier night than tonight. */
export function fromEarlierNight(iso: string): boolean {
  return nightOf(iso) < nightOf(Date.now())
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
 * may mark a photo; one shared answer saves six calls on a weak signal. The answer is
 * also kept on the phone for this sign-in, so Stands still knows which reservation
 * is yours with no signal (audit A-18). */
export function whoAmI(): Promise<Me> {
  const token = getToken()
  if (meCache && meCache.token === token && Date.now() - meCache.at < 3_600_000) return meCache.p
  const entry = { token, at: Date.now(), p: null as unknown as Promise<Me> }
  entry.p = api<Me>('/auth/me', { timeoutMs: 20_000 }).then(
    (me) => {
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

function savedMe(token: string | null): Me | null {
  try {
    const v = JSON.parse(localStorage.getItem(ME_KEY) || 'null')
    return v && token && v.token === token ? (v.me as Me) : null
  } catch {
    return null
  }
}

export async function login(email: string, password: string): Promise<void> {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(data.access_token)
}
