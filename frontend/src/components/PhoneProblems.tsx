import { useEffect, useState } from 'react'
import { type Failure, api, whenLabel } from '../api'
import { type Key, t } from '../i18n'
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
const PAGES: [string, Key][] = [
  ['/photos', 'nav.photos'], ['/stands', 'nav.stands'], ['/cameras', 'nav.cameras'], ['/map', 'nav.map'], ['/insights', 'nav.insights'],
  ['/animals', 'nav.animals'], ['/settings', 'nav.settings'], ['/sit/', 'nav.sitMode'], ['/login', 'nav.signIn'],
]
const pageOf = (route: string) => {
  if (route === '/') return t('nav.tonight')
  const page = PAGES.find(([p]) => route.startsWith(p))?.[1]
  return page ? t(page) : route
}

const KIND: Record<string, Key> = {
  chunk: 'problems.chunk',
  render: 'problems.render',
  error: 'problems.error',
  rejection: 'problems.error',
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
      .catch((e: Failure) => setErr(e.offline ? t('problems.noSignal') : t('problems.couldnt', { why: e.message })))
  }
  useEffect(load, [])

  const summary = rows == null ? undefined : rows.length === 0 ? t('problems.none') : t('problems.lately', { count: rows.length })
  return (
    <SettingsSection id="problems" title={t('problems.title')} summary={summary}>
      <p className="settings-hint">{t('problems.hint')}</p>
      {err && <div role="alert" style={{ fontSize: 13, color: 'var(--text-dim)' }}>{err}<button className="text-action" onClick={load}>{t('common.tryAgain')}</button></div>}
      {!err && rows == null && <div role="status" style={{ fontSize: 13, color: 'var(--text-dim)' }}>{t('common.loading')}</div>}
      {rows?.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>{t('problems.nothing')}</div>}
      {rows?.map((r) => (
        <div key={r.id} className="phone-problem">
          <div className="phone-problem-head">
            <span>{t(KIND[r.kind] ?? 'problems.error')}</span>
            <span className="phone-problem-when">{r.at ? whenLabel(r.at) : ''}</span>
          </div>
          <div className="phone-problem-who">
            {r.who} · {r.device}{r.route ? ` · ${pageOf(r.route)}` : ''}
          </div>
          <div className="phone-problem-msg">{r.message}</div>
          {(r.stack || r.build || late(r)) && (
            <details className="phone-problem-more">
              <summary>{t('problems.details')}</summary>
              {late(r) && <div>{t('problems.sentLate', { when: whenLabel(r.reported_at!) })}</div>}
              {r.build && <div>{t('problems.build', { build: r.build })}</div>}
              {r.stack && <pre>{r.stack}</pre>}
            </details>
          )}
        </div>
      ))}
    </SettingsSection>
  )
}
