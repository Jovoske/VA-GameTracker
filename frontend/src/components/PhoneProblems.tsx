import { useEffect, useState } from 'react'
import { type Failure, api, whenLabel } from '../api'
import SettingsSection from './SettingsSection'

/**
 * Admins only: what broke on hunters' phones lately, as the app reported it
 * (src/crash.ts, /api/client-errors). The newest few, with who, which phone, which
 * page and when; the technical detail behind a fold for whoever fixes it.
 */
type Report = {
  id: string
  // When it happened on the phone; reported_at is when it reached the server.
  at: string | null
  reported_at: string | null
  kind: string
  message: string
  stack: string | null
  route: string | null
  build: string | null
  device: string
  who: string
}

// Which page it was on, in the tab bar's words.
const PAGES: [string, string][] = [
  ['/photos', 'Photos'], ['/stands', 'Stands'], ['/cameras', 'Cameras'], ['/map', 'Map'], ['/insights', 'Insights'],
  ['/animals', 'Animals'], ['/settings', 'Settings'], ['/sit/', 'Sit mode'], ['/login', 'Sign in'],
]
const pageOf = (route: string) => (route === '/' ? 'Tonight' : PAGES.find(([p]) => route.startsWith(p))?.[1] ?? route)

const KIND: Record<string, string> = {
  chunk: 'A page didn’t load',
  render: 'A page broke',
  error: 'Error',
  rejection: 'Error',
}

// Waited on the phone for signal: worth saying when it finally arrived.
const late = (r: Report) => !!(r.at && r.reported_at && Date.parse(r.reported_at) - Date.parse(r.at) > 10 * 60_000)

export default function PhoneProblems() {
  const [rows, setRows] = useState<Report[] | null>(null)
  const [err, setErr] = useState('')

  function load() {
    setErr('')
    api<Report[]>('/client-errors?limit=10', { timeoutMs: 20_000 })
      .then(setRows)
      .catch((e: Failure) => setErr(e.offline ? 'No signal, so the list didn’t load.' : `Couldn’t load the list. ${e.message}`))
  }
  useEffect(load, [])

  const summary = rows == null ? undefined : rows.length === 0 ? 'None' : `${rows.length} lately`
  return (
    <SettingsSection id="problems" title="Problems on phones" summary={summary}>
      <p className="settings-hint">When the app breaks on someone’s phone it reports it here, newest first.</p>
      {err && <div role="alert" style={{ fontSize: 13, color: 'var(--text-dim)' }}>{err}<button className="text-action" onClick={load}>Try again</button></div>}
      {!err && rows == null && <div role="status" style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</div>}
      {rows?.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Nothing reported.</div>}
      {rows?.map((r) => (
        <div key={r.id} className="phone-problem">
          <div className="phone-problem-head">
            <span>{KIND[r.kind] ?? 'Error'}</span>
            <span className="phone-problem-when">{r.at ? whenLabel(r.at) : ''}</span>
          </div>
          <div className="phone-problem-who">
            {r.who} · {r.device}{r.route ? ` · ${pageOf(r.route)}` : ''}
          </div>
          <div className="phone-problem-msg">{r.message}</div>
          {(r.stack || r.build || late(r)) && (
            <details className="phone-problem-more">
              <summary>Details</summary>
              {late(r) && <div>Sent {whenLabel(r.reported_at!)}, when the phone had signal</div>}
              {r.build && <div>Build {r.build}</div>}
              {r.stack && <pre>{r.stack}</pre>}
            </details>
          )}
        </div>
      ))}
    </SettingsSection>
  )
}
