import { useEffect, useState } from 'react'
import { api } from '../api'

type Overview = {
  totals: { sightings: number; empty: number; nights: number; cameras: number }
  by_hour: { hour: number; count: number }[]
  by_camera: { name: string; sightings: number }[]
  best_window: { start_hour: number; end_hour: number; share_pct: number }
  tonight: {
    moon_phase: string
    moon_illum: number
    darkness_minutes: number | null
    most_active_camera: string | null
  }
}

const hh = (n: number) => String(n).padStart(2, '0') + ':00'

export default function Tonight() {
  const [d, setD] = useState<Overview | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api<Overview>('/analytics/overview').then(setD).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div style={{ color: 'var(--text-dim)' }}>Couldn't load analytics: {err}</div>
  if (!d) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>

  const maxH = Math.max(...d.by_hour.map((x) => x.count), 1)
  const maxCam = Math.max(...d.by_camera.map((x) => x.sightings), 1)
  const bw = d.best_window
  const t = d.tonight
  const inWindow = (hr: number) =>
    bw.start_hour <= bw.end_hour
      ? hr >= bw.start_hour && hr < bw.end_hour
      : hr >= bw.start_hour || hr < bw.end_hour

  const labelStyle = {
    fontSize: 12,
    color: 'var(--text-dim)',
    letterSpacing: '.05em',
    marginBottom: 12,
  } as const

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Tonight</div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>BEST BET TONIGHT · from {d.totals.sightings} sightings</div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
          <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--go)', fontVariantNumeric: 'tabular-nums' }}>
            {hh(bw.start_hour)}–{hh(bw.end_hour)}
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>{bw.share_pct}% of all activity</div>
        </div>
        <div style={{ fontSize: 14, marginBottom: 12 }}>
          Hottest camera: <span style={{ fontWeight: 600 }}>{t.most_active_camera ?? '—'}</span>
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, color: 'var(--text-dim)' }}>
          <span>🌙 {t.moon_phase} · {t.moon_illum}% lit</span>
          {t.darkness_minutes != null && <span>🌑 {Math.round(t.darkness_minutes / 60)}h of darkness</span>}
        </div>
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>ACTIVITY BY HOUR · local time (peak window in green)</div>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 120 }}>
          {d.by_hour.map((x) => (
            <div
              key={x.hour}
              title={`${hh(x.hour)} — ${x.count} sightings`}
              style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}
            >
              <div
                style={{
                  height: `${(x.count / maxH) * 100}%`,
                  minHeight: x.count ? 2 : 0,
                  background: inWindow(x.hour) ? 'var(--go)' : 'var(--surface-2)',
                  borderRadius: '3px 3px 0 0',
                }}
              />
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 2, marginTop: 4 }}>
          {d.by_hour.map((x) => (
            <div key={x.hour} style={{ flex: 1, textAlign: 'center', fontSize: 9, color: 'var(--text-dim)' }}>
              {x.hour % 6 === 0 ? x.hour : ''}
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>SIGHTINGS BY CAMERA</div>
        {d.by_camera.map((c) => (
          <div key={c.name} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{ width: 130, fontSize: 13 }}>{c.name}</div>
            <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ width: `${(c.sightings / maxCam) * 100}%`, height: '100%', background: 'var(--teal)' }} />
            </div>
            <div style={{ width: 36, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>
              {c.sightings}
            </div>
          </div>
        ))}
      </div>

      <div style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', lineHeight: 1.6 }}>
        {d.totals.sightings} animal sightings · {d.totals.empty} empty frames filtered · {d.totals.nights} nights of data
        <br />
        Species ID and the full forecast model come next — this is your real activity pattern so far.
      </div>
    </div>
  )
}
