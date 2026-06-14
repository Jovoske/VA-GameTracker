import { useEffect, useState } from 'react'
import { api } from '../api'

type Insights = {
  outlook: {
    date: string
    moon_phase: string
    moon_illum: number
    darkness_minutes: number | null
    camera: string | null
    species: string | null
    probability: number | null
    verdict: string
  }[]
  composition: { label: string; count: number; top_camera: string | null }[]
  correlations: { statement: string; strength: number; sample: number }[]
}

const verdictColor = (v: string) =>
  v === 'GO' ? 'var(--go)' : v === 'MARGINAL' ? 'var(--marginal)' : 'var(--skip)'
const dayName = (iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short' })
const dayNum = (iso: string) => new Date(iso + 'T12:00:00').getDate()
const labelStyle = { fontSize: 12, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 12 } as const

export default function Insights() {
  const [d, setD] = useState<Insights | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api<Insights>('/insights').then(setD).catch((e) => setErr(e.message))
  }, [])

  if (err) return <div style={{ color: 'var(--text-dim)' }}>Couldn't load: {err}</div>
  if (!d) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Insights</div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>7-NIGHT OUTLOOK</div>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
          {d.outlook.map((o) => (
            <div
              key={o.date}
              style={{
                flex: '1 0 68px',
                textAlign: 'center',
                padding: '8px 4px',
                borderRadius: 8,
                background: 'var(--surface-2)',
                borderTop: `2px solid ${verdictColor(o.verdict)}`,
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {dayName(o.date)} {dayNum(o.date)}
              </div>
              <div style={{ fontSize: 12, fontWeight: 700, color: verdictColor(o.verdict), margin: '4px 0' }}>
                {o.verdict}
              </div>
              <div style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {o.species ?? '—'}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>
                {o.probability != null ? Math.round(o.probability * 100) + '%' : '–'}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 3 }}>
                🌙 {Math.round(o.moon_illum)}%
              </div>
            </div>
          ))}
        </div>
      </div>

      {d.composition && d.composition.length > 0 && (
        <div className="card" style={{ padding: 18, marginBottom: 14 }}>
          <div style={labelStyle}>HERD MAKEUP · WHERE</div>
          {(() => {
            const max = Math.max(...d.composition.map((x) => x.count), 1)
            return d.composition.slice(0, 8).map((x) => (
              <div key={x.label} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <div style={{ width: 104, fontSize: 13 }}>{x.label}</div>
                <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${(x.count / max) * 100}%`, height: '100%', background: 'var(--teal)' }} />
                </div>
                <div style={{ width: 28, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{x.count}</div>
                <div style={{ width: 92, fontSize: 11, color: 'var(--text-dim)', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={x.top_camera ?? ''}>
                  {x.top_camera}
                </div>
              </div>
            ))
          })()}
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
            Stags vs hinds, sows with piglets vs sounders — and the stand each favours.
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>PATTERNS</div>
        {d.correlations.length === 0 && (
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>Not enough data yet to call patterns.</div>
        )}
        {d.correlations.map((c, i) => (
          <div
            key={i}
            style={{
              marginBottom: 12,
              paddingBottom: 12,
              borderBottom: i < d.correlations.length - 1 ? '1px solid var(--border)' : 'none',
            }}
          >
            <div style={{ fontSize: 14, lineHeight: 1.4 }}>{c.statement}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
              <div style={{ flex: 1, maxWidth: 140, height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, c.strength * 100)}%`, height: '100%', background: 'var(--teal)' }} />
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>based on {c.sample} sightings</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ color: 'var(--text-dim)', fontSize: 11, textAlign: 'center' }}>
        Early patterns from ~1 month of data — they firm up over the season.
      </div>
    </div>
  )
}
