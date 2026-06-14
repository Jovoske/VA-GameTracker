import { useEffect, useState } from 'react'
import { api } from '../api'

type Status = {
  cameras: number
  images: number
  detections: number
  empty: number
  last_sync: { status: string; at: string | null } | null
}
type Check = {
  current: string
  latest: string | null
  update_available?: boolean
  update_command?: string
  error?: string
}
const labelStyle = { fontSize: 12, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 12 } as const

export default function Admin() {
  const [version, setVersion] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [check, setCheck] = useState<Check | null>(null)
  const [checking, setChecking] = useState(false)
  const [sexMsg, setSexMsg] = useState('')
  const [sexBusy, setSexBusy] = useState(false)

  async function runSexPass() {
    setSexBusy(true)
    try {
      const r = await api<{ note?: string }>('/admin/sex-pass', { method: 'POST' })
      setSexMsg(r.note || 'Started.')
    } catch (e) {
      setSexMsg((e as Error).message)
    }
    setSexBusy(false)
  }

  useEffect(() => {
    api<{ version: string }>('/admin/version').then((r) => setVersion(r.version)).catch(() => {})
    api<Status>('/admin/status').then(setStatus).catch(() => {})
  }, [])

  async function checkUpdates() {
    setChecking(true)
    try {
      setCheck(await api<Check>('/admin/version/check'))
    } catch {
      /* ignore */
    }
    setChecking(false)
  }

  const rows: [string, number][] = status
    ? [
        ['Cameras', status.cameras],
        ['Photos', status.images],
        ['Detections', status.detections],
        ['Empty frames filtered', status.empty],
      ]
    : []

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Settings</div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>VERSION</div>
        <div style={{ fontSize: 16, fontWeight: 600 }}>GameSense v{version || '…'}</div>
        <button
          className="btn"
          style={{ width: 'auto', marginTop: 12, padding: '8px 14px' }}
          onClick={checkUpdates}
          disabled={checking}
        >
          {checking ? 'Checking…' : 'Check for updates'}
        </button>
        {check && (
          <div style={{ marginTop: 12, fontSize: 13 }}>
            {check.error ? (
              <span style={{ color: 'var(--text-dim)' }}>Couldn't reach GitHub: {check.error}</span>
            ) : check.update_available ? (
              <>
                <div style={{ color: 'var(--go)' }}>
                  Update available: {check.latest} (you have {check.current})
                </div>
                <div style={{ color: 'var(--text-dim)', marginTop: 6 }}>To update, run on the host:</div>
                <code
                  style={{
                    display: 'block',
                    background: 'var(--surface-2)',
                    padding: '8px 10px',
                    borderRadius: 8,
                    marginTop: 4,
                    fontSize: 12,
                    fontFamily: 'var(--font-mono, monospace)',
                  }}
                >
                  {check.update_command}
                </code>
              </>
            ) : (
              <span style={{ color: 'var(--text-dim)' }}>Up to date ({check.current}).</span>
            )}
          </div>
        )}
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>AI LABELLING</div>
        <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 10 }}>
          Identify sex on red deer (stag / hind) and wild boar using cloud vision. Uses your
          ANTHROPIC_API_KEY and costs a little API credit per photo; only un-sexed animals are processed.
        </div>
        <button
          className="btn"
          style={{ width: 'auto', padding: '8px 14px' }}
          onClick={runSexPass}
          disabled={sexBusy}
        >
          {sexBusy ? 'Starting…' : 'Identify deer / boar sex'}
        </button>
        {sexMsg && <div style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{sexMsg}</div>}
      </div>

      {status && (
        <div className="card" style={{ padding: 18 }}>
          <div style={labelStyle}>SYSTEM</div>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{k}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
            </div>
          ))}
          {status.last_sync && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>Last sync</span>
              <span>{status.last_sync.status}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
