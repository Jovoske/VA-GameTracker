import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { LAST_EMAIL_KEY, getToken, login, safeNext } from '../api'
import LanguagePicker from '../components/LanguagePicker'
import { t } from '../i18n'

export default function Login() {
  const nav = useNavigate()
  const params = new URLSearchParams(window.location.search)
  const expired = params.has('expired')
  // The page to go back to: the photo an alert opened, or where the sign-in ran out.
  const next = safeNext(params.get('next'))
  // Whoever signed in last on this phone, never a guess: the admin's address used to
  // be filled in for every visitor to the public page (audit D-06).
  const [email, setEmail] = useState(() => {
    try { return localStorage.getItem(LAST_EMAIL_KEY) ?? '' } catch { return '' }
  })
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Already signed in (Back from Tonight lands here): straight on, not a sign-in form
  // that looks like being signed out (audit D-16).
  if (getToken() && !busy) return <Navigate to={next} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await login(email, password)
      // Replacing the sign-in page, so Back from there never comes back to it.
      nav(next, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('login.couldnt'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page" style={{ minHeight: '100%', display: 'grid', gridTemplateColumns: 'minmax(0, 340px)', justifyContent: 'center', justifyItems: 'center', alignContent: 'center', gap: 16, padding: 24 }}>
      <form onSubmit={onSubmit} className="card" style={{ width: '100%', padding: 24 }}>
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
            {t('api.signedOut')}
          </div>
        )}

        <label htmlFor="login-email" style={{ fontSize: 12, color: 'var(--text-dim)' }}>{t('login.email')}</label>
        <input
          id="login-email"
          className="input"
          style={{ margin: '6px 0 14px' }}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          autoFocus={!email}
        />

        <label htmlFor="login-password" style={{ fontSize: 12, color: 'var(--text-dim)' }}>{t('login.password')}</label>
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
          {busy ? t('login.signingIn') : t('nav.signIn')}
        </button>
      </form>
      <LanguagePicker compact />
    </div>
  )
}
