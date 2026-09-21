import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ageLabel, api, apiCached } from '../api'
import { useRefetchOnReturn, useReveal } from '../hooks'
import './tonight.css'

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
  reason?: string
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
type SpeciesOpt = { id: string; common_name: string; huntable: boolean; detections: number }

const hh = (n: number) => String(n).padStart(2, '0') + ':00'
const hours = (w: { start_hour: number; end_hour: number }) => `${hh(w.start_hour)} to ${hh(w.end_hour)}`

// Verdict states are carried by word and shape; colour is a third channel.
const VERDICTS: Record<Verdict, { label: string; glyph: string; color: string }> = {
  BEST_ODDS: { label: 'Best odds', glyph: '▲', color: 'var(--v-best)' },
  WORTH_A_LOOK: { label: 'Worth a look', glyph: '◐', color: 'var(--v-look)' },
  QUIET: { label: 'Quiet', glyph: '○', color: 'var(--v-quiet)' },
  NO_DATA: { label: 'Not enough to say', glyph: '▨', color: 'var(--v-quiet)' },
}
const verdictOf = (v: string) => VERDICTS[v as Verdict] ?? VERDICTS.NO_DATA
const verdictColor = (v: string) => verdictOf(v).color
const compass = (deg: number) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(deg / 45) % 8]
const impactColor = (impact: string) =>
  impact.startsWith('+') ? 'var(--go)' : impact === '•' ? 'var(--text-dim)' : 'var(--marginal)'

export default function Tonight() {
  const [d, setD] = useState<Overview | null>(null)
  const [f, setF] = useState<Forecast | null>(null)
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [err, setErr] = useState('')
  const requestId = useRef(0)
  const [planAt, setPlanAt] = useState<string | null>(null)
  // True while a species chip has changed the question but the answer has not
  // caught up yet.
  const [settling, setSettling] = useState(false)

  // Which animals the verdict is ranked for. Empty = every species left on in
  // Settings. Kept in localStorage because it is a standing preference.
  const [species, setSpecies] = useState<SpeciesOpt[]>([])
  const [picked, setPicked] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('gs_species_filter') || '[]')
    } catch {
      return []
    }
  })

  function load(sel: string[] = picked, settle = false) {
    const request = ++requestId.current
    setErr('')
    const q = sel.length ? `?species=${encodeURIComponent(sel.join(','))}` : ''
    if (settle) setSettling(true)
    // Paint from the last good plan first; refresh underneath. No signal in the
    // valley still gets a verdict, labelled with its age.
    apiCached<Forecast>(`/forecast/tonight${q}`)
      .then(({ data, at }) => {
        if (request !== requestId.current) return
        setF(data)
        setPlanAt(at)
      })
      .catch((e) => {
        if (request !== requestId.current) return
        setErr(e.message)
        if (settle) setF(null)
      })
      .finally(() => { if (request === requestId.current) setSettling(false) })
    api<Overview>('/analytics/overview').then(setD).catch(() => setD(null))
    api<Alert[]>('/alerts').then(setAlerts).catch(() => {})
    // Refetched with the plan, so a species switched on in Settings shows up here
    // on the way back without a reload.
    api<SpeciesOpt[]>('/species')
      .then((all) => setSpecies(all.filter((s) => s.huntable && s.detections > 0)))
      .catch(() => {})
  }
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useRefetchOnReturn(() => load())

  function toggleSpecies(id: string) {
    const next = picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]
    setPicked(next)
    localStorage.setItem('gs_species_filter', JSON.stringify(next))
    load(next, true)
  }
  function pickAll() {
    setPicked([])
    localStorage.setItem('gs_species_filter', '[]')
    load([], true)
  }

  const verdictIn = useReveal(!!f)
  const grown = useReveal(!!d)

  if (err && !f) return <div className="status-panel" role="alert">Could not load tonight's plan: {err}<button className="text-action" onClick={() => load()}>Try again</button></div>
  if (!f) return <div className="status-panel" role="status">Working out tonight…</div>

  const c = f.conditions
  const r = f.recommended
  const v = verdictOf(f.verdict)
  const maxH = Math.max(...(d?.by_hour ?? []).map((x) => x.count), 1)
  const maxCam = Math.max(...(d?.by_camera ?? []).map((x) => x.sightings), 1)
  const maxSp = Math.max(...(d?.by_species ?? []).map((x) => x.count), 1)
  const bw = d?.best_window ?? { start_hour: 0, end_hour: 0, share_pct: 0 }
  const inWindow = (hr: number) =>
    bw.start_hour <= bw.end_hour ? hr >= bw.start_hour && hr < bw.end_hour : hr >= bw.start_hour || hr < bw.end_hour
  const stale = planAt ? Date.now() - new Date(planAt).getTime() > 12 * 3600e3 : false
  const hasNumbers = !!(f.where && f.where.length > 0) || !!f.calibration?.statement || !!d

  return (
    <div className="tonight">
      <h1 className="page-title">Tonight</h1>
      {err && <div className="status-panel" role="alert">Could not refresh. Showing the last plan.<button className="text-action" onClick={() => load()}>Try again</button></div>}

      {/* Which animals the ground is ranked for. Chips list only species left on
          in Settings that the cameras have actually recorded. */}
      {species.length > 0 && (
        <div className="tn-after" role="group" aria-label="I'm after">
          <div className="tn-after-label" aria-hidden="true">I'm after</div>
          <div className="tn-chips">
            <button className="tn-chip" aria-pressed={picked.length === 0} onClick={pickAll}>
              Anything
            </button>
            {species.map((s) => (
              <button
                key={s.id}
                className="tn-chip"
                aria-pressed={picked.includes(s.id)}
                onClick={() => toggleSpecies(s.id)}
                title={`${s.detections} sightings`}
              >
                {s.common_name}
              </button>
            ))}
            <Link to="/settings" className="tn-chip-edit">Edit list</Link>
          </div>
        </div>
      )}

      {planAt && (
        <p className="tn-fresh" data-stale={stale}>
          Plan from {ageLabel(planAt)}{stale ? ', may be out of date' : ''}
        </p>
      )}

      {/* ── The decision ───────────────────────────── */}
      <section
        className={`card tn-verdict hero-enter${settling ? ' settling' : ''}`}
        data-in={verdictIn}
        style={{ borderTop: `3px solid ${v.color}` }}
        aria-labelledby="tn-verdict-h"
      >
        <div className="tn-verdict-head">
          <span className="tn-verdict-glyph" style={{ color: v.color }} aria-hidden="true">{v.glyph}</span>
          <div>
            <h2 id="tn-verdict-h" className="tn-verdict-label">{v.label}</h2>
            {r && <div className="tn-verdict-cam">{r.camera}</div>}
          </div>
        </div>

        {!r && f.reason && <p className="tn-reason">{f.reason}</p>}

        {r && (
          <>
            <div className="tn-hours"><small>Best hours</small>{hours(r.best_window)}</div>
            <div className="tn-species">{r.species}</div>
            <div className="tn-reason">{r.reason}</div>
            <div className="tn-caveat">{r.caveat}</div>

            {f.wind?.text && (
              <div className="tn-line">
                <span className="tn-line-k">Wind</span>
                <span
                  className="tn-line-v"
                  data-tone={f.wind.status === 'scent_carries' ? 'warn' : undefined}
                  data-soft={!f.wind.is_advice}
                >
                  {f.wind.text}
                </span>
              </div>
            )}

            {f.changed?.text && (
              <div className="tn-line">
                <span className="tn-line-k">Changed</span>
                <span className="tn-line-v" data-tone={f.changed.kind === 'camera_down' ? 'down' : undefined}>
                  {f.changed.text}
                </span>
              </div>
            )}

            <div className="tn-cond">
              {c.moon_illum != null && <span>{c.moon_illum}% moon</span>}
              {c.darkness_minutes != null && <span>{Math.round(c.darkness_minutes / 60)} h of dark</span>}
              {c.wind_dir_deg != null && (
                <span>Wind {compass(c.wind_dir_deg)} {Math.round(c.wind_speed_kmh ?? 0)} km/h</span>
              )}
            </div>

            {f.factors && f.factors.length > 0 && (
              <div className="tn-why">
                <h3 className="sect" style={{ marginBottom: 8 }}>Why</h3>
                {f.factors.map((fac, i) => (
                  <div key={i} className="tn-why-row">
                    <span className="tn-why-impact" style={{ color: impactColor(fac.impact) }}>{fac.impact}</span>
                    <span style={{ flex: 1 }}>{fac.text}</span>
                  </div>
                ))}
              </div>
            )}

            {r.classes && r.classes.length > 0 && (
              <>
                <h3 className="sect" style={{ marginTop: 14, marginBottom: 6 }}>Seen here</h3>
                <div className="tn-classes" style={{ marginTop: 0 }}>
                  {r.classes.map((cl) => (
                    <span key={cl.label} className="tn-class">
                      {cl.label} <span>×{cl.count}</span>
                    </span>
                  ))}
                </div>
              </>
            )}
          </>
        )}

        {f.alternates.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <h3 className="sect" style={{ marginBottom: 8 }}>Other places</h3>
            <div className="tn-alts">
              {f.alternates.map((a) => (
                <div key={a.camera} className="tn-alt">
                  <span className="tn-alt-glyph" style={{ color: verdictColor(a.verdict) }} aria-hidden="true">
                    {verdictOf(a.verdict).glyph}
                  </span>
                  <span className="tn-alt-name">{a.camera} · {a.species}</span>
                  <span className="tn-alt-seen">Seen {a.nights_present} of {a.active_nights} nights</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="tn-foot">
          From {f.nights_of_data} nights of camera photos.
          {f.exposure?.note && <> {f.exposure.note}</>}
        </div>
      </section>

      {/* Cameras that are not sending. Their silence is a hardware fact, not an
          empty wood, so it is reported rather than folded into the ranking. */}
      {f.alerts && f.alerts.length > 0 && (
        <section className="card tn-card" aria-labelledby="tn-cams-h">
          <h2 id="tn-cams-h" className="sect">Cameras not sending</h2>
          {f.alerts.map((a) => (
            <div key={a.camera} className="tn-camrow">
              <span className="tn-camrow-name">{a.camera}</span>
              <span className="tn-camrow-detail">{a.detail}</span>
            </div>
          ))}
          <div className="tn-note">These are ranked on what they saw before they stopped.</div>
        </section>
      )}

      {alerts.length > 0 && (
        <section className="card tn-card" aria-labelledby="tn-alerts-h">
          <h2 id="tn-alerts-h" className="sect">Alerts</h2>
          {alerts.map((a, i) => {
            const col =
              a.severity === 'high' ? 'var(--go)' : a.severity === 'warn' ? 'var(--marginal)' : 'var(--teal)'
            return (
              <div key={i} className="tn-alert">
                <span className="tn-alert-dot" style={{ background: col }} aria-hidden="true" />
                <div>
                  <div className="tn-alert-title">{a.title}</div>
                  <div className="tn-alert-text">{a.text}</div>
                </div>
              </div>
            )
          })}
        </section>
      )}

      {/* ── The numbers, folded away ───────────────── */}
      {hasNumbers && (
        <details className="tn-details">
          <summary>Show the numbers</summary>

          {f.where && f.where.length > 0 && (
            <div className={`block${settling ? ' settling' : ''}`}>
              <h2 className="sect">Every camera</h2>
              {f.where.map((w) => (
                <div key={w.camera} className="tn-where">
                  <span className="tn-where-glyph" style={{ color: verdictColor(w.verdict) }} aria-hidden="true">
                    {verdictOf(w.verdict).glyph}
                  </span>
                  <div style={{ flex: 1 }}>
                    <div className="tn-where-head">
                      <span className="tn-where-name">{w.camera}</span>
                      <span className="tn-where-verdict" style={{ color: verdictColor(w.verdict) }}>
                        {verdictOf(w.verdict).label}
                      </span>
                      <span className="tn-where-meta">{hours(w.best_window)}</span>
                      <span className="tn-where-meta">Seen {w.nights_present} of {w.active_nights} nights</span>
                    </div>
                    <div className="tn-classes" style={{ marginTop: 5 }}>
                      {w.classes.length === 0 && <span className="tn-where-meta">No group type identified</span>}
                      {w.classes.map((cl) => (
                        <span key={cl.label} className="tn-class">
                          {cl.label} <span>×{cl.count}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              <div className="tn-note" style={{ marginTop: 4 }}>
                Counts are photos, not animals. The same animal can show up many times.
              </div>
            </div>
          )}

          {f.calibration?.statement && (
            <div className="block">
              <h2 className="sect">How often this has been right</h2>
              <div style={{ fontSize: 13, lineHeight: 1.5 }}>{f.calibration.statement}</div>
            </div>
          )}

          {d && (
            <>
              <div className="block">
                <h2 className="sect">Sightings by hour <span className="sect-note">busiest hours in green</span></h2>
                <div className="tn-bars-y">
                  {d.by_hour.map((x) => (
                    <div key={x.hour} title={`${hh(x.hour)}: ${x.count}`}>
                      <div className="bar-y" style={{ height: `${(x.count / maxH) * 100}%`, minHeight: x.count ? 2 : 0, background: inWindow(x.hour) ? 'var(--go)' : 'var(--surface-2)', borderRadius: 'var(--r-chip) var(--r-chip) 0 0', transform: `scaleY(${grown ? 1 : 0})` }} />
                    </div>
                  ))}
                </div>
                <div className="tn-bars-x">
                  {d.by_hour.map((x) => (
                    <div key={x.hour}>{x.hour % 6 === 0 ? x.hour : ''}</div>
                  ))}
                </div>
              </div>

              <div className="block">
                <h2 className="sect">Sightings by camera</h2>
                {d.by_camera.map((cam) => (
                  <div key={cam.name} className="tn-hrow">
                    <div className="tn-hrow-name">{cam.name}</div>
                    <div className="tn-hrow-track">
                      <div className="bar-x" style={{ width: '100%', height: '100%', background: 'var(--teal)', transform: `scaleX(${grown ? cam.sightings / maxCam : 0})` }} />
                    </div>
                    <div className="tn-hrow-n">{cam.sightings}</div>
                  </div>
                ))}
              </div>

              {d.by_species.length > 0 && (
                <div className="block">
                  <h2 className="sect">Sightings by animal</h2>
                  {d.by_species.slice(0, 8).map((s) => (
                    <div key={s.species} className="tn-hrow">
                      <div className="tn-hrow-name">{s.species}</div>
                      <div className="tn-hrow-track">
                        <div className="bar-x" style={{ width: '100%', height: '100%', background: 'var(--sand)', transform: `scaleX(${grown ? s.count / maxSp : 0})` }} />
                      </div>
                      <div className="tn-hrow-n">{s.count}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className="tn-totals">
                {d.totals.sightings} photos with animals · {d.totals.empty} empty photos set aside · {d.totals.nights} nights
              </div>
            </>
          )}
        </details>
      )}
    </div>
  )
}
