import { type FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'

export default function Login() {
  const nav = useNavigate()
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
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ minHeight: '100%', display: 'grid', placeItems: 'center', padding: 24 }}>
      <form onSubmit={onSubmit} className="card" style={{ width: 340, padding: 24 }}>
        <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 4 }}>
          Game<span style={{ color: 'var(--go)' }}>Sense</span>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 13, marginBottom: 20 }}>
          Turn your trail cameras into a hunting forecast.
        </div>

        <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Email</label>
        <input
          className="input"
          style={{ margin: '6px 0 14px' }}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
        />

        <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>Password</label>
        <input
          className="input"
          style={{ margin: '6px 0 14px' }}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {error && <div style={{ color: 'var(--skip)', fontSize: 13, marginBottom: 12 }}>{error}</div>}

        <button className="btn" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
