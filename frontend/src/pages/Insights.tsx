import { useEffect, useState } from 'react'
import { api, imageUrl } from '../api'
import { useRefetchOnReturn } from '../hooks'

type Insights = {
  outlook: {
    date: string
    moon_phase: string
    moon_illum: number
    darkness_minutes: number | null
    sunset: string | null
    civil_twilight_end: string | null
  }[]
  composition: { label: string; count: number; top_camera: string | null }[]
  correlations: { statement: string; strength: number; sample: number }[]
}
type ClassImg = { image_id: string; file_url: string; captured_at: string; camera: string; group_size: number | null }
type Driver = {
  factor: string
  statement: string
  effect_pct: number
  sample_nights: number
  confidence: number
  buckets: { label: string; rate: number }[]
  correlation: number
}
type PScope = {
  key: string
  label: string
  drivers: Driver[]
  active_nights: number
  total_nights: number
  avg_per_night: number
  sightings: number
}
type Patterns = { scopes: PScope[]; nights: number; range?: [string, string] }

const dayName =(iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short' })
const dayNum = (iso: string) => new Date(iso + 'T12:00:00').getDate()
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '–'
const labelStyle = { fontSize: 12, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 12 } as const

export default function Insights() {
  const [d, setD] = useState<Insights | null>(null)
  const [err, setErr] = useState('')
  const [openClass, setOpenClass] = useState<string | null>(null)
  const [classImgs, setClassImgs] = useState<ClassImg[] | null>(null)
  const [zoom, setZoom] = useState<string | null>(null)
  const [pat, setPat] = useState<Patterns | null>(null)
  const [patScope, setPatScope] = useState('all')

  function load() {
    api<Insights>('/insights').then(setD).catch((e) => setErr(e.message))
    api<Patterns>('/insights/patterns').then(setPat).catch(() => {})
  }
  useEffect(load, [])
  useRefetchOnReturn(load, 120_000)

  async function openClassImages(label: string) {
    setOpenClass(label)
    setClassImgs(null)
    try {
      setClassImgs(await api<ClassImg[]>('/insights/class?label=' + encodeURIComponent(label)))
    } catch {
      setClassImgs([])
    }
  }
  function closeClass() {
    setOpenClass(null)
    setClassImgs(null)
  }

  if (err) return <div style={{ color: 'var(--text-dim)' }}>Couldn't load: {err}</div>
  if (!d) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Insights</div>

      <div className="card" style={{ padding: 18, marginBottom: 14 }}>
        <div style={labelStyle}>NEXT 7 NIGHTS · SUN &amp; MOON</div>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
          {d.outlook.map((o) => (
            <div
              key={o.date}
              title={`${o.moon_phase} · last light ${clock(o.civil_twilight_end)}`}
              style={{
                flex: '1 0 68px',
                textAlign: 'center',
                padding: '8px 4px',
                borderRadius: 8,
                background: 'var(--surface-2)',
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {dayName(o.date)} {dayNum(o.date)}
              </div>
              <div style={{ fontSize: 14, margin: '4px 0' }}>🌙</div>
              <div style={{ fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                {Math.round(o.moon_illum)}%
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 3 }}>
                {clock(o.civil_twilight_end)}
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10, lineHeight: 1.45 }}>
          Moon illumination and last shootable light. No odds here on purpose — a night seven
          days out can't be called until the forecast has been scored against what the cameras
          actually saw. Tonight's call lives on the Tonight tab.
        </div>
      </div>

      {d.composition && d.composition.length > 0 && (
        <div className="card" style={{ padding: 18, marginBottom: 14 }}>
          <div style={labelStyle}>HERD MAKEUP · WHERE</div>
          {(() => {
            const max = Math.max(...d.composition.map((x) => x.count), 1)
            return d.composition.slice(0, 8).map((x) => (
              <div
                key={x.label}
                onClick={() => openClassImages(x.label)}
                title={`View the ${x.count} ${x.label} photos`}
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, cursor: 'pointer' }}
              >
                <div style={{ width: 100, fontSize: 13 }}>{x.label}</div>
                <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${(x.count / max) * 100}%`, height: '100%', background: 'var(--teal)' }} />
                </div>
                <div style={{ width: 28, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{x.count}</div>
                <div style={{ width: 88, fontSize: 11, color: 'var(--text-dim)', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={x.top_camera ?? ''}>
                  {x.top_camera}
                </div>
                <span style={{ color: 'var(--text-dim)', fontSize: 15, lineHeight: 1 }}>›</span>
              </div>
            ))
          })()}
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
            Stags vs hinds, sows with piglets vs sounders — and the stand each favours.
          </div>
        </div>
      )}

      {pat && pat.scopes.length > 0 && (() => {
        const sc = pat.scopes.find((s) => s.key === patScope) || pat.scopes[0]
        const maxRate = Math.max(...sc.drivers.flatMap((d) => d.buckets.map((b) => b.rate)), 1)
        return (
          <div className="card" style={{ padding: 18, marginBottom: 14 }}>
            <div style={labelStyle}>BEHAVIOUR DRIVERS · WEATHER &amp; MOON</div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
              {pat.scopes.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setPatScope(s.key)}
                  style={{
                    fontSize: 12, padding: '4px 10px', borderRadius: 8, cursor: 'pointer',
                    border: '1px solid var(--border)',
                    background: s.key === sc.key ? 'var(--surface-2)' : 'transparent',
                    color: s.key === sc.key ? 'var(--text)' : 'var(--text-dim)',
                    fontWeight: s.key === sc.key ? 600 : 400,
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {sc.drivers.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>No clear weather/moon driver yet — needs more nights.</div>
            )}
            {sc.drivers.map((dr, i) => (
              <div key={i} style={{ marginBottom: 14, paddingBottom: 14, borderBottom: i < sc.drivers.length - 1 ? '1px solid var(--border)' : 'none' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontSize: 12, color: 'var(--text-dim)', minWidth: 92 }}>{dr.factor}</span>
                  <span style={{ fontSize: 14, flex: 1, lineHeight: 1.4 }}>
                    {dr.statement}
                    {dr.confidence < 0.4 && (
                      <span
                        title="Weak signal so far — treat as a hint, not a rule"
                        style={{
                          marginLeft: 8, fontSize: 10, fontWeight: 700, letterSpacing: '.03em',
                          color: 'var(--sand)', border: '1px solid var(--border)',
                          borderRadius: 5, padding: '1px 6px', verticalAlign: 'middle',
                        }}
                      >
                        EARLY SIGNAL
                      </span>
                    )}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, marginTop: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 32 }} title="sightings/night: low → high range of this factor">
                    {dr.buckets.map((b) => (
                      <div key={b.label} title={`${b.label}: ${b.rate}/night`} style={{ width: 13, height: `${(b.rate / maxRate) * 100}%`, minHeight: 2, background: 'var(--teal)', borderRadius: '2px 2px 0 0' }} />
                    ))}
                  </div>
                  <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ flex: 1, maxWidth: 120, height: 4, background: 'var(--surface-2)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${dr.confidence * 100}%`, height: '100%', background: 'var(--sand)' }} />
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>{Math.round(dr.confidence * 100)}% confidence · {dr.sample_nights} nights</span>
                  </div>
                </div>
              </div>
            ))}
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
              {sc.label}: {sc.sightings} sightings over {pat.nights} weather-backtracked nights (avg {sc.avg_per_night}/night). A
              running calculation — it sharpens as more nights feed in.
            </div>
          </div>
        )
      })()}

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

      {openClass && (
        <div
          onClick={closeClass}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 50, display: 'flex', padding: 16 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="card"
            style={{ padding: 0, maxWidth: 760, width: '100%', margin: 'auto', overflow: 'hidden', display: 'flex', flexDirection: 'column', maxHeight: '90vh' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontWeight: 700, fontSize: 15 }}>{openClass}</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {classImgs ? `${classImgs.length} sighting${classImgs.length === 1 ? '' : 's'}` : 'loading…'}
              </span>
              <button
                onClick={closeClass}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text-dim)', borderRadius: 8, padding: '4px 10px', cursor: 'pointer', fontSize: 13 }}
              >
                Close
              </button>
            </div>
            <div style={{ overflowY: 'auto', padding: 12 }}>
              {!classImgs && <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading…</div>}
              {classImgs && classImgs.length === 0 && (
                <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>No photos.</div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
                {classImgs?.map((im) => (
                  <div
                    key={im.image_id}
                    onClick={() => setZoom(imageUrl(im.file_url))}
                    style={{ background: 'var(--surface-2)', borderRadius: 8, overflow: 'hidden', cursor: 'pointer' }}
                  >
                    <img src={imageUrl(im.file_url)} loading="lazy" alt={openClass} style={{ width: '100%', height: 104, objectFit: 'cover', display: 'block' }} />
                    <div style={{ padding: '4px 7px', fontSize: 11, color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{im.camera}</span>
                      <span>{new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {zoom && (
        <div
          onClick={() => setZoom(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.92)', zIndex: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
        >
          <img src={zoom} alt="" style={{ maxWidth: '94vw', maxHeight: '94vh', borderRadius: 10 }} />
        </div>
      )}
    </div>
  )
}
