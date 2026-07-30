const TOKEN_KEY = 'gs_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

/** Add the session token to an <img> src.
 *
 * Image bytes are behind authentication now — trail cameras photograph people, not
 * only animals — but an <img> tag cannot send an Authorization header, so the token
 * rides in the query string instead.
 */
export function authedImageUrl(url: string | null | undefined): string {
  if (!url) return ''
  const token = getToken()
  if (!token) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

/** Last-good copy of a GET response, so the plan survives a dead valley.
 *
 * The service worker replays cached API responses, but only for an installed PWA
 * that has the worker running. This is the belt to that braces: a plain
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

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const resp = await fetch(`/api${path}`, { ...options, headers })
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}))
    throw new Error(detail.detail || `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

export async function login(email: string, password: string): Promise<void> {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(data.access_token)
}
