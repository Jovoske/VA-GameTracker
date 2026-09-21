import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'

export default function Login() {
  const nav = useNavigate()
  const expired = new URLSearchParams(window.location.search).has('expired')
  const [email, setEmail] = useState('admin@gamesense.local')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password)
      nav('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't sign in")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ minHeight: '100%', display: 'grid', placeItems: 'center', padding: 24 }}>
      <form onSubmit={onSubmit} className="card" style={{ width: 340, maxWidth: '100%', padding: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 20 }}>
          Game<span style={{ color: 'var(--go)' }}>Sense</span>
        </div>

        {expired && (
          <div
            role="status"
            style={{
              fontSize: 13,
              color: 'var(--sand)',
              background: 'var(--surface-2)',
              borderRadius: 'var(--r-ctl)',
              padding: '8px 11px',
              marginBottom: 16,
              lineHeight: 1.45,
            }}
          >
            You were signed out. Sign in again.
          </div>
        )}

        <label htmlFor="login-email" style={{ fontSize: 12, color: 'var(--text-dim)' }}>Email</label>
        <input
          id="login-email"
          className="input"
          style={{ margin: '6px 0 14px' }}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
        />

        <label htmlFor="login-password" style={{ fontSize: 12, color: 'var(--text-dim)' }}>Password</label>
        <input
          id="login-password"
          className="input"
          style={{ margin: '6px 0 14px' }}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {error && <div role="alert" style={{ color: 'var(--skip)', fontSize: 13, marginBottom: 12 }}>{error}</div>}

        <button className="btn" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
