const TOKEN_KEY = 'gs_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Content-Type', 'application/json')
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const resp = await fetch(`/api${path}`, { ...options, headers })

  // An expired or revoked session is not a data-loading failure — showing it as one
  // leaves the user staring at a red error with no way forward. Clear the dead token
  // and send them to sign in. Only when we actually sent a token: a 401 without one is
  // a failed login attempt, which the login form reports itself.
  if (resp.status === 401 && token) {
    setToken(null)
    if (!window.location.pathname.startsWith('/login')) {
      window.location.assign('/login?expired=1')
    }
    throw new Error('Session expired — please sign in again')
  }

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
