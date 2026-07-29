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
