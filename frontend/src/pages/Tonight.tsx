import { useEffect, useState } from 'react'
import { api } from '../api'

export default function Tonight() {
  const [apiOk, setApiOk] = useState<boolean | null>(null)

  useEffect(() => {
    api<{ status: string }>('/health')
      .then((r) => setApiOk(r.status === 'ok'))
      .catch(() => setApiOk(false))
  }, [])

  return (
    <div style={{ maxWidth: 480, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Tonight</div>
      <div className="card" style={{ padding: 20, textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>🌒</div>
        <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 6 }}>Still learning your ground</div>
        <div style={{ color: 'var(--text-dim)', fontSize: 14, lineHeight: 1.5, marginBottom: 16 }}>
          GameSense needs about 30 nights of data before the Tonight verdict (GO / MARGINAL / SKIP)
          becomes reliable. Nothing is faked before then.
        </div>
        <div style={{ height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
          <div style={{ width: '5%', height: '100%', background: 'var(--go)' }} />
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
          Gathering data — cameras now syncing
        </div>
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', marginTop: 16 }}>
        API status: {apiOk === null ? 'checking…' : apiOk ? '● connected' : '● unreachable'}
      </div>
    </div>
  )
}
