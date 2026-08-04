import { useEffect, useState } from 'react'
import { ageLabel, api, apiCached } from '../api'
import { useRefetchOnReturn } from '../hooks'

type Overview = {
  totals: { sightings: number; empty: number; nights: number; cameras: number }
  by_hour: { hour: number; count: number }[]
  by_camera: { name: string; sightings: number }[]
  by_species: { species: string; count: number }[]
  best_window: { start_hour: number; end_hour: number; share_pct: number }
}

type ClassCount = { label: string; count: number }
type Verdict = 'BEST_ODDS' | 'WORTH_A_LOOK' | 'QUIET' | 'NO_DATA'
type Changed = { kind: string; camera: string | null; text: string }
type Wind = { status: string; text: string; is_advice: boolean }
type Calibration = { available: boolean; n_evaluated: number; statement?: string; beats_baseline?: boolean }
type Forecast = {
  verdict: Verdict
  changed?: Changed
  wind?: Wind
  calibration?: Calibration
  recommended?: {
    camera: string
    species: string
    runner_up: string | null
    probability: number
    best_window: { start_hour: number; end_hour: number }
    expect?: string
    classes?: ClassCount[]
    nights_present: number
    active_nights: number
    reason: string
    caveat: string
  }
  conditions: {
    moon_phase: string
    moon_illum: number | null
    darkness_minutes: number | null
    wind_dir_deg: number | null
    wind_speed_kmh: number | null
  }
  factors?: { text: string; impact: string }[]
  where?: {
    camera: string
    verdict: Verdict
    probability: number
    nights_present: number
    active_nights: number
    best_window: { start_hour: number; end_hour: number }
    classes: ClassCount[]
  }[]
  alternates: {
    camera: string
    species: string
    verdict: Verdict
    nights_present: number
    active_nights: number
  }[]
  alerts?: { camera: string; status: string; detail: string }[]
  exposure?: { excluded_nights: number; note: string }
  nights_of_data: number
}

type Alert = { type: string; severity: string; title: string; text: string }

const hh = (n: number) => String(n).padStart(2, '0') + ':00'

// Verdict states are carried by WORD and SHAPE; colour is a redundant third channel.
// GO/MARGINAL/SKIP were also commands, which turns every blank evening into a broken
// promise. These describe the ground and leave the decision with the hunter.
const VERDICTS: Record<Verdict, { label: string; glyph: string; color: string }> = {
  BEST_ODDS: { label: 'BEST ODDS', glyph: '▲', color: 'var(--v-best)' },
  WORTH_A_LOOK: { label: 'WORTH A LOOK', glyph: '◐', color: 'var(--v-look)' },
  QUIET: { label: 'QUIET', glyph: '○', color: 'var(--v-quiet)' },
  NO_DATA: { label: 'NO DATA', glyph: '▨', color: 'var(--v-quiet)' },
}
const verdictOf = (v: string) => VERDICTS[v as Verdict] ?? VERDICTS.NO_DATA
const verdictColor = (v: string) => verdictOf(v).color
const compass = (deg: number) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(deg / 45) % 8]
const labelStyle = { fontSize: 12, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 12 } as const
const impactColor = (impact: string) =>
  impact.startsWith('+') ? 'var(--go)' : impact === '•' ? 'var(--text-dim)' : 'var(--marginal)'

export default function Tonight() {
  const [d, setD] = useState<Overview | null>(null)
  const [f, setF] = useState<Forecast | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [err, setErr] = useState('')
  const [planAt, setPlanAt] = useState<string | null>(null)

  function load() {
    // Paint from the last good plan first; refresh underneath. A hunter in a valley
    // with no bars still gets the verdict, clearly labelled with its age.
    apiCached<Forecast>('/forecast/tonight')
      .then(({ data, at }) => {
        setF(data)
        setPlanAt(at)
      })
      .catch((e) => setErr(e.message))
    api<Overview>('/analytics/overview').then(setD).catch((e) => setErr(e.message))
    api<Alert[]>('/alerts').then(setAlerts).catch(() => {})
  }
  useEffect(load, [])
  useRefetchOnReturn(load)

  if (err) return <div style={{ color: 'var(--text-dim)' }}>Couldn't load: {err}</div>
  if (!f) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>

  const c = f.conditions
  const r = f.recommended
  const vc = verdictColor(f.verdict)
  const maxH = Math.max(...(d?.by_hour ?? []).map((x) => x.count), 1)
  const maxCam = Math.max(...(d?.by_camera ?? []).map((x) => x.sightings), 1)
  const maxSp = Math.max(...(d?.by_species ?? []).map((x) => x.count), 1)
  const bw = d?.best_window ?? { start_hour: 0, end_hour: 0, share_pct: 0 }
  const inWindow = (hr: number) =>
    bw.start_hour <= bw.end_hour ? hr >= bw.start_hour && hr < bw.end_hour : hr >= bw.start_hour || hr < bw.end_hour

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Tonight</div>

      {/* Age of what you are reading. In decision support the freshness of the data
          IS data; a stale plan presented as current is the failure mode. */}
      {planAt && (
        <div
          style={{
            fontSize: 12,
            padding: '7px 12px',
            marginBottom: 12,
            borderRadius: 8,
            background: 'var(--surface-2)',
            color: 'var(--text-dim)',
            border: `1px solid ${
              Date.now() - new Date(planAt).getTime() > 12 * 3600e3 ? 'var(--v-look)' : 'var(--border)'
            }`,
          }}
        >
          Plan from {ageLabel(planAt)}
        </div>
      )}

      {alerts.length > 0 && (
        <div className="card" style={{ padding: 14, marginBottom: 14 }}>
          <div style={labelStyle}>ALERTS</div>
          {alerts.map((a, i) => {
            const col =
              a.severity === 'high' ? 'var(--go)' : a.severity === 'warn' ? 'var(--marginal)' : 'var(--teal)'
            return (
              <div
                key={i}
                style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: i < alerts.length - 1 ? 10 : 0 }}
              >
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: col, marginTop: 5, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{a.title}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{a.text}</div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Cameras that aren't sending. Their silence is not evidence of no animals, so
          it is reported as a hardware fact rather than folded into the ranking. */}
      {f.alerts && f.alerts.length > 0 && (
        <div className="card" style={{ padding: 14, marginBottom: 14 }}>
          <div style={labelStyle}>CAMERAS NOT REPORTING</div>
          {f.alerts.map((a, i) => (
            <div
              key={a.camera}
              style={{ display: 'flex', gap: 10, alignItems: 'baseline', marginBottom: i < (f.alerts?.length ?? 0) - 1 ? 8 : 0 }}
            >
              <span style={{ fontSize: 13, fontWeight: 600, minWidth: 96 }}>{a.camera}</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)', flex: 1 }}>{a.detail}</span>
            </div>
          ))}
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.45 }}>
            These stands keep their historical ranking — a camera out of photo credits still
            has animals in front of it.
          </div>
        </div>
      )}

      {/* ── Verdict hero ───────────────────────────── */}
      <div className="card" style={{ padding: 18, marginBottom: 14, borderTop: `3px solid ${vc}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 22, color: vc, lineHeight: 1 }}>{verdictOf(f.verdict).glyph}</span>
          <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '.02em' }}>
            {verdictOf(f.verdict).label}
            {r && <span style={{ color: 'var(--text-dim)' }}> · {r.camera}</span>}
          </div>
        </div>

        {r && (
          <>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 12 }}>{r.species}</div>
            {/* Natural frequency, reference class inside the sentence. No headline
                percentage: a percentage reads as "my chance of a shot tonight", which
                is not what was measured. */}
            <div style={{ fontSize: 14, marginTop: 4, lineHeight: 1.45 }}>{r.reason}</div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4, lineHeight: 1.45 }}>{r.caveat}</div>

            {/* Wind, with its competence boundary stated. Dimmed when the app is
                declining to call it, so "too light to call" never reads like advice. */}
            {f.wind?.text && (
              <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'baseline' }}>
                <span style={{ fontSize: 10, letterSpacing: '.06em', color: 'var(--text-dim)', flexShrink: 0 }}>
                  WIND
                </span>
                <span
                  style={{
                    fontSize: 14,
                    lineHeight: 1.45,
                    color: f.wind.status === 'scent_carries' ? 'var(--v-look)' : 'var(--text)',
                    opacity: f.wind.is_advice ? 1 : 0.7,
                  }}
                >
                  {f.wind.text}
                </span>
              </div>
            )}

            {/* The one comparison a hunter cannot make from memory. Never blank: a
                decision aid that goes silent teaches the user that silence means
                broken, so "nothing changed" is said out loud. */}
            {f.changed?.text && (
              <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'baseline' }}>
                <span style={{ fontSize: 10, letterSpacing: '.06em', color: 'var(--text-dim)', flexShrink: 0 }}>
                  CHANGED
                </span>
                <span
                  style={{
                    fontSize: 14,
                    lineHeight: 1.45,
                    color: f.changed.kind === 'camera_down' ? 'var(--marginal)' : 'var(--text)',
                  }}
                >
                  {f.changed.text}
                </span>
              </div>
            )}

            {r.classes && r.classes.length > 0 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                {r.classes.map((cl) => (
                  <span key={cl.label} style={{ fontSize: 12, background: 'var(--surface-2)', borderRadius: 6, padding: '2px 8px' }}>
                    {cl.label} <span style={{ color: 'var(--text-dim)' }}>×{cl.count}</span>
                  </span>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 13, marginTop: 12 }}>
              <span style={{ color: 'var(--go)', fontWeight: 600 }}>
                {hh(r.best_window.start_hour)}–{hh(r.best_window.end_hour)}
              </span>
              {c.moon_illum != null && <span style={{ color: 'var(--text-dim)' }}>🌙 {c.moon_illum}%</span>}
              {c.darkness_minutes != null && (
                <span style={{ color: 'var(--text-dim)' }}>🌑 {Math.round(c.darkness_minutes / 60)}h</span>
              )}
              {c.wind_dir_deg != null && (
                <span style={{ color: 'var(--text-dim)' }}>
                  💨 {compass(c.wind_dir_deg)} {Math.round(c.wind_speed_kmh ?? 0)}km/h
                </span>
              )}
            </div>

            {f.factors && f.factors.length > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ fontSize: 11, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 8 }}>
                  WHY
                </div>
                {f.factors.map((fac, i) => (
                  <div key={i} style={{ display: 'flex', gap: 8, fontSize: 13, marginBottom: 6 }}>
                    <span style={{ color: impactColor(fac.impact), fontVariantNumeric: 'tabular-nums', minWidth: 26 }}>
                      {fac.impact}
                    </span>
                    <span style={{ flex: 1 }}>{fac.text}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {f.alternates.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, color: 'var(--text-dim)', letterSpacing: '.05em', marginBottom: 8 }}>
              OTHER STANDS
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {f.alternates.map((a) => (
                <div
                  key={a.camera}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'var(--surface-2)', borderRadius: 8, padding: '8px 11px' }}
                >
                  <span style={{ color: verdictColor(a.verdict), fontSize: 13, width: 14, flexShrink: 0 }}>
                    {verdictOf(a.verdict).glyph}
                  </span>
                  <span style={{ flex: 1, fontSize: 13 }}>
                    {a.camera} · {a.species}
                  </span>
                  {/* A fraction, not a percentage — the sample size stays visible. */}
                  <span style={{ fontSize: 12, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                    {a.nights_present}/{a.active_nights} nights
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 14, lineHeight: 1.5 }}>
          Early forecast from {f.nights_of_data} nights — it sharpens as more accumulate.
          {/* An exclusion nobody is told about is indistinguishable from the bug it
              replaced, so the count is stated rather than quietly applied. */}
          {f.exposure?.note && <> {f.exposure.note}</>}
        </div>
      </div>

      {/* ── What to expect, by stand ───────────────── */}
      {f.where && f.where.length > 0 && (
        <div className="card" style={{ padding: 18, marginBottom: 14 }}>
          <div style={labelStyle}>WHAT TO EXPECT · BY STAND</div>
          {f.where.map((w) => (
            <div key={w.camera} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 12 }}>
              <span style={{ color: verdictColor(w.verdict), fontSize: 13, width: 14, marginTop: 3, flexShrink: 0 }}>
                {verdictOf(w.verdict).glyph}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>{w.camera}</span>
                  <span style={{ fontSize: 12, color: verdictColor(w.verdict), fontWeight: 600 }}>
                    {verdictOf(w.verdict).label}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                    {hh(w.best_window.start_hour)}–{hh(w.best_window.end_hour)}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                    {w.nights_present}/{w.active_nights} nights
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 5 }}>
                  {w.classes.length === 0 && <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>—</span>}
                  {w.classes.map((cl) => (
                    <span key={cl.label} style={{ fontSize: 12, background: 'var(--surface-2)', borderRadius: 6, padding: '2px 8px' }}>
                      {cl.label} <span style={{ color: 'var(--text-dim)' }}>×{cl.count}</span>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
            Classes seen at each stand — stags vs hinds, sows with piglets — from sexed &amp; grouped sightings.
          </div>
        </div>
      )}

      {/* Track record: what replaced the invented confidence figure. It is a measured
          hit rate against camera-nights, and it is withheld entirely until there is
          enough scored history for it to mean anything. */}
      {f.calibration?.statement && (
        <div className="card" style={{ padding: 14, marginBottom: 14 }}>
          <div style={labelStyle}>TRACK RECORD</div>
          <div style={{ fontSize: 13, lineHeight: 1.5 }}>{f.calibration.statement}</div>
        </div>
      )}

      {d && (
        <>
          {/* ── Activity by hour ───────────────────────── */}
          <div className="card" style={{ padding: 18, marginBottom: 14 }}>
            <div style={labelStyle}>ACTIVITY BY HOUR · local time (peak window in green)</div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 120 }}>
              {d.by_hour.map((x) => (
                <div key={x.hour} title={`${hh(x.hour)} — ${x.count}`} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
                  <div style={{ height: `${(x.count / maxH) * 100}%`, minHeight: x.count ? 2 : 0, background: inWindow(x.hour) ? 'var(--go)' : 'var(--surface-2)', borderRadius: '3px 3px 0 0' }} />
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

          {/* ── By camera ──────────────────────────────── */}
          <div className="card" style={{ padding: 18, marginBottom: 14 }}>
            <div style={labelStyle}>SIGHTINGS BY CAMERA</div>
            {d.by_camera.map((cam) => (
              <div key={cam.name} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <div style={{ width: 130, fontSize: 13 }}>{cam.name}</div>
                <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${(cam.sightings / maxCam) * 100}%`, height: '100%', background: 'var(--teal)' }} />
                </div>
                <div style={{ width: 36, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{cam.sightings}</div>
              </div>
            ))}
          </div>

          {/* ── By species ─────────────────────────────── */}
          {d.by_species.length > 0 && (
            <div className="card" style={{ padding: 18, marginBottom: 14 }}>
              <div style={labelStyle}>SPECIES</div>
              {d.by_species.slice(0, 8).map((s) => (
                <div key={s.species} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <div style={{ width: 130, fontSize: 13 }}>{s.species}</div>
                  <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{ width: `${(s.count / maxSp) * 100}%`, height: '100%', background: 'var(--sand)' }} />
                  </div>
                  <div style={{ width: 36, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{s.count}</div>
                </div>
              ))}
            </div>
          )}

          <div style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', lineHeight: 1.6 }}>
            {d.totals.sightings} animal sightings · {d.totals.empty} empty frames filtered · {d.totals.nights} nights of data
          </div>
        </>
      )}
    </div>
  )
}
