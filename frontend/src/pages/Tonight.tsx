import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  type Failure,
  type Got,
  ageLabel,
  fromEarlierNight,
  getFresh,
  nightOf,
  noAnswer,
  noAnswerWords,
  peek,
} from '../api'
import PhotoFreshness, { type Freshness } from '../components/PhotoFreshness'
import HarvestPrompt from '../components/Harvest'
import SitPrompts from '../components/SitPrompts'
import { isCall } from '../map/geometry'
import { useRefetchOnReturn, useReveal } from '../hooks'
import './tonight.css'

type Overview = {
  totals: { sightings: number; empty: number; nights: number; cameras: number }
  by_hour: { hour: number; count: number }[]
  by_camera: { id?: string; name: string; sightings: number }[]
  by_species: { species: string; count: number }[]
  best_window: { start_hour: number; end_hour: number; share_pct: number }
}

// Visits: arrivals at the camera, so one sow loitering for forty frames counts once.
// `count` is what a plan saved before visits were counted still carries.
type ClassCount = { label: string; visits?: number; photos?: number; count?: number }
type Verdict = 'BEST_ODDS' | 'WORTH_A_LOOK' | 'QUIET' | 'NO_DATA'
type Changed = { kind: string; camera: string | null; text: string }
// One verdict for a stand, as the map, Stands and Sit mode give it, for the sit time
// (`at_local`: 45 min after sunset, or `now` once that has passed).
type Wind = { status: string; text: string; is_advice: boolean; at_local?: string; now?: boolean; stand?: string | null }
// Clock times on the estate's clock ("20:45"); the hours are what an older plan carries.
// None when the animals were never seen at an hour somebody can sit.
type Window = { start_hour: number; end_hour: number; start?: string; end?: string } | null
// How each verdict turned out: "When it said Best odds, animals came 7 of 9 nights."
type Calibration = { available: boolean; n_evaluated: number; statement?: string; lines?: string[]; beats_baseline?: boolean | null }
type Forecast = {
  verdict: Verdict
  reason?: string
  changed?: Changed
  wind?: Wind
  calibration?: Calibration
  recommended?: {
    camera: string
    camera_id?: string
    species: string
    runner_up: string | null
    probability: number
    best_window: Window
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
    sunset_local?: string | null
    // When Open-Meteo made the forecast, and whether it is an old copy (no answer since).
    forecast_fetched_at?: string | null
    forecast_stale?: boolean
  }
  factors?: { text: string; impact: string }[]
  where?: {
    camera: string
    camera_id?: string
    verdict: Verdict
    visits?: number
    photos?: number
    probability: number
    nights_present: number
    active_nights: number
    best_window: Window
    classes: ClassCount[]
  }[]
  alternates: {
    camera: string
    camera_id?: string
    species: string
    verdict: Verdict
    nights_present: number
    active_nights: number
  }[]
  // `ranked`: still in the plan on what it saw before it stopped; false once it has
  // sent nothing for over a week.
  alerts?: { camera: string; camera_id?: string; status: string; detail: string; ranked?: boolean }[]
  exposure?: { excluded_nights: number; note: string }
  nights_of_data: number
  freshness?: Freshness | null
}

type Alert = { type: string; severity: string; title: string; text: string; camera?: string }
type SpeciesOpt = { id: string; common_name: string; huntable: boolean; detections: number }

const hh = (n: number) => String(n).padStart(2, '0') + ':00'
const hours = (w: Window) => w ? `${w.start ?? hh(w.start_hour)} to ${w.end ?? hh(w.end_hour)}` : 'Not seen when you can sit'
/** Which stand and when the wind line is for: "Puente, for 20:41" or "Puente, now".
 *  Only a call has a time: "isn't on the map yet" is not a verdict for 20:41. */
const windFor = (w: Wind) => [w.stand, isCall(w.status) && (w.now ? 'now' : w.at_local && `for ${w.at_local}`)].filter(Boolean).join(', ')
const estateTime = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' })
const visitsOf = (cl: ClassCount) => cl.visits ?? cl.count ?? 0
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

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

const PICK_KEY = 'gs_species_filter'
// A plan left on screen through the evening asks again this often, and its age
// label moves on every minute (audit I-24).
const REFRESH_EVERY_MS = 15 * 60_000
// "The numbers" don't change by the minute and cost the server the most (G-19).
const OVERVIEW_EVERY_MS = 10 * 60_000

const planPath = (sel: string[]) => `/forecast/tonight${sel.length ? `?species=${encodeURIComponent(sel.join(','))}` : ''}`

function readPick(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(PICK_KEY) || '[]')
    return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
  } catch {
    return []
  }
}
function savePick(sel: string[]) {
  try { localStorage.setItem(PICK_KEY, JSON.stringify(sel)) } catch { /* private mode */ }
}
const huntable = (all: SpeciesOpt[]) => all.filter((s) => s.huntable && s.detections > 0)
const samePick = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))

export default function Tonight() {
  // Which animals the verdict is ranked for. Empty = every species left on in
  // Settings. Kept in localStorage because it is a standing preference.
  const [picked, setPicked] = useState<string[]>(readPick)
  const pickedRef = useRef(picked)
  pickedRef.current = picked
  // The pick the plan on screen answers. The chips can be ahead of it while a new
  // question is out; only an answer moves this, and only this is saved, so a tap
  // that never got an answer (no signal, the hunter left) can't strand the next
  // launch on a pick with no saved plan (audit A-15).
  const confirmed = useRef(picked)

  // The saved plan is painted first, with its real age, and the network replaces
  // it when it answers. On one bar of signal that is the plan in a second instead
  // of a spinner for minutes (audit A-05, D-03).
  const [plan, setPlan] = useState<Got<Forecast> | null>(() => peek<Forecast>(planPath(picked)))
  const [d, setD] = useState<Overview | null>(() => peek<Overview>('/analytics/overview')?.data ?? null)
  const [alerts, setAlerts] = useState<Alert[]>(() => peek<Alert[]>('/alerts')?.data ?? [])
  const [species, setSpecies] = useState<SpeciesOpt[]>(() => huntable(peek<SpeciesOpt[]>('/species')?.data ?? []))
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [checking, setChecking] = useState(true)
  // True while a species chip has changed the question but the answer has not
  // caught up yet.
  const [settling, setSettling] = useState(false)
  const [, setTick] = useState(0)

  const planRef = useRef(plan)
  planRef.current = plan
  const planCtl = useRef<AbortController | null>(null)
  const restCtl = useRef<AbortController | null>(null)
  const lastLoad = useRef(0)

  /** Ask for the plan. A newer question cancels the one before it. A question
   *  the chips asked that can't be answered goes back to the plan on screen. */
  function loadPlan(sel: string[]) {
    planCtl.current?.abort()
    const ctl = new AbortController()
    planCtl.current = ctl
    setChecking(true)
    getFresh<Forecast>(planPath(sel), { signal: ctl.signal, save: true })
      .then((got) => {
        if (ctl.signal.aborted) return
        setPlan(got)
        keepPick(sel)
        setErr('')
      })
      .catch((e: Failure) => {
        if (ctl.signal.aborted) return
        if (!samePick(sel, confirmed.current)) {
          setPicked(confirmed.current)
          const why = noAnswer(e)
          setNotice(`${why ? noAnswerWords(why) : `Couldn’t switch. ${e.message}`} Still showing the plan you had.`)
          if (planRef.current) return
        }
        setErr(e.message)
      })
      .finally(() => {
        if (planCtl.current !== ctl) return
        setChecking(false)
        setSettling(false)
      })
  }

  /** Everything around the plan. None of it depends on the chips (G-19). */
  function loadRest() {
    restCtl.current?.abort()
    const ctl = new AbortController()
    restCtl.current = ctl
    const opts = { signal: ctl.signal }
    const had = peek<Overview>('/analytics/overview')
    if (!had || Date.now() - Date.parse(had.at) > OVERVIEW_EVERY_MS) {
      getFresh<Overview>('/analytics/overview', opts).then((got) => setD(got.data)).catch(() => {})
    }
    // Last night's alerts are not tonight's: an old copy is dropped, not shown.
    getFresh<Alert[]>('/alerts', opts)
      .then((got) => setAlerts(got.stale && fromEarlierNight(got.at) ? [] : got.data))
      .catch(() => {})
    // Refetched with the plan, so a species switched on in Settings shows up here
    // on the way back without a reload. Saved, so the chips are there with no signal.
    getFresh<SpeciesOpt[]>('/species', { ...opts, save: true })
      .then((got) => {
        const offered = huntable(got.data)
        setSpecies(offered)
        if (got.stale) return
        // A saved pick of an animal no longer offered (turned off or hidden in
        // Settings) filtered the plan invisibly, with no chip lit (A-16, I-07).
        // Drop it; with nothing left that is "Anything".
        const ids = new Set(offered.map((s) => s.id))
        const kept = pickedRef.current.filter((id) => ids.has(id))
        if (kept.length === pickedRef.current.length) return
        // The old pick is no question to go back to, so this one stands at once.
        setPicked(kept)
        keepPick(kept)
        const hit = peek<Forecast>(planPath(kept))
        if (hit) setPlan(hit)
        loadPlan(kept)
      })
      .catch(() => {})
  }

  function load() {
    lastLoad.current = Date.now()
    loadPlan(pickedRef.current)
    loadRest()
  }
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    loadRef.current()
    const tick = window.setInterval(() => {
      setTick((n) => n + 1)
      if (document.visibilityState === 'visible' && Date.now() - lastLoad.current > REFRESH_EVERY_MS) loadRef.current()
    }, 60_000)
    // Leaving the page drops what it was still asking for: on a thin link the next
    // tab should not queue behind this one (K-08).
    return () => {
      window.clearInterval(tick)
      planCtl.current?.abort()
      restCtl.current?.abort()
    }
  }, [])
  useRefetchOnReturn(() => load())

  /** The plan on screen now answers `sel`: that is the pick to keep. */
  function keepPick(sel: string[]) {
    confirmed.current = sel
    savePick(sel)
  }

  /** A chip changes the question. The answer saved for it, if any, shows at once;
   *  with nothing saved and no signal, the chips go back and the plan stays (A-15). */
  function switchTo(next: string[]) {
    setPicked(next)
    setNotice('')
    const hit = peek<Forecast>(planPath(next))
    if (hit) {
      setPlan(hit)
      keepPick(next)
    }
    setSettling(!hit)
    loadPlan(next)
  }
  function toggleSpecies(id: string) {
    switchTo(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id])
  }
  function pickAll() {
    switchTo([])
  }

  const f = plan?.data ?? null
  const verdictIn = useReveal(!!f)
  const grown = useReveal(!!d)

  /* Which animals the ground is ranked for. Chips list only species left on in
     Settings that the cameras have actually recorded. Also on the "could not load"
     screen: the plan saved for another pick ("Anything") is one tap away. */
  const chips = species.length > 0 && (
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
  )
  const noticeLine = notice && <div className="status-panel" role="status">{notice}<button className="text-action" onClick={() => setNotice('')}>OK</button></div>

  // Your sit, before the plan: "Back to sit" after the phone closed the app mid-sit,
  // and "What happened last night?" in the morning, then the morning's "log what you
  // shot" (the harvest book). With no plan saved and no signal, the way back into the
  // seat must still be there. Same place in every state below, so the plan arriving
  // doesn't start it over.
  const top = <><h1 className="page-title">Tonight</h1><SitPrompts page="tonight" /><HarvestPrompt /></>

  if (!f && err) return (
    <div className="tonight">
      {top}
      <div className="status-panel" role="alert">Could not load tonight's plan: {err}<button className="text-action" onClick={() => load()}>Try again</button></div>
      {noticeLine}
      {chips}
    </div>
  )
  if (!f) return <div className="tonight">{top}<div className="status-panel" role="status">Working out tonight…</div></div>

  const c = f.conditions
  const r = f.recommended
  const v = verdictOf(f.verdict)
  const maxH = Math.max(...(d?.by_hour ?? []).map((x) => x.count), 1)
  const maxCam = Math.max(...(d?.by_camera ?? []).map((x) => x.sightings), 1)
  const maxSp = Math.max(...(d?.by_species ?? []).map((x) => x.count), 1)
  // The green band is the headline's Best hours, so the chart can't name other ones
  // (audit A-26). Without a recommendation there is no band.
  const bw = r?.best_window
  const inWindow = (hr: number) => !!bw && (
    bw.start_hour <= bw.end_hour ? hr >= bw.start_hour && hr < bw.end_hour : hr >= bw.start_hour || hr < bw.end_hour)
  // Made before this morning's 06:00: that was an earlier night's plan.
  const old = fromEarlierNight(plan!.at)
  const oldWords = nightOf(plan!.at) === nightOf(Date.now() - 86_400_000) ? 'last night' : 'an earlier night'
  const hasNumbers = !!(f.where && f.where.length > 0) || !!f.calibration?.statement || !!d
  // A camera the Changed line is already about isn't said again under Alerts as
  // "quiet" (audit G-23). The server uses one rule for both, so "Nothing changed"
  // never has a quiet camera beside it; a plan kept from earlier (no signal) could,
  // and then the line wins.
  const nothingChanged = f.changed?.kind === 'none' && !!f.changed.text
  const shownAlerts = alerts.filter((a) => !(a.type === 'quiet' && (nothingChanged || (a.camera && a.camera === f.changed?.camera))))

  return (
    <div className="tonight">
      {top}
      {err && <div className="status-panel" role="alert">Could not refresh: {err} Showing the last plan.<button className="text-action" onClick={() => load()}>Try again</button></div>}
      {noticeLine}
      {chips}

      {/* How old the plan on screen really is. A saved copy says why it is on
          screen ("No signal."), and one from an earlier night says so. */}
      <p className="tn-fresh" data-stale={old || plan!.stale} role={plan!.stale ? 'status' : undefined}>
        {plan!.stale && <>{noAnswerWords(plan!.why)} </>}
        Plan from {ageLabel(plan!.at)}{old ? `, made for ${oldWords}. It may be out of date.` : '.'}
        {checking && !plan!.stale && ageLabel(plan!.at) !== 'just now' && ' Checking for a newer one…'}
        {plan!.stale && !checking && <button className="tn-fresh-retry" onClick={() => load()}>Try again</button>}
      </p>
      <PhotoFreshness freshness={f.freshness} />

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
        {!r && c.sunset_local && <div className="tn-sunset">Sunset {c.sunset_local}</div>}

        {r && (
          <>
            <div className="tn-hours" data-none={!r.best_window || undefined}><small>Best hours</small>{hours(r.best_window)}</div>
            {c.sunset_local && <div className="tn-sunset">Sunset {c.sunset_local}</div>}
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
                  {windFor(f.wind) && <span className="tn-line-when">{windFor(f.wind)}</span>}
                  {c.forecast_stale && c.forecast_fetched_at && (
                    <span className="tn-line-when">No newer forecast: this one is from {estateTime(c.forecast_fetched_at)}.</span>
                  )}
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
                      {cl.label} <span>{plural(visitsOf(cl), 'visit')}</span>
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
                <div key={a.camera_id ?? a.camera} className="tn-alt">
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
          {f.nights_of_data > 0
            ? `From ${plural(f.nights_of_data, 'night')} the cameras were watching.`
            : 'No nights of camera photos yet.'}
          {f.exposure?.note && <> {f.exposure.note}</>}
        </div>
      </section>

      {/* Cameras that are not sending. Their silence is a hardware fact, not an
          empty wood, so it is reported rather than folded into the ranking. */}
      {f.alerts && f.alerts.length > 0 && (
        <section className="card tn-card" aria-labelledby="tn-cams-h">
          <h2 id="tn-cams-h" className="sect">Cameras not sending</h2>
          {f.alerts.map((a) => (
            <div key={a.camera_id ?? a.camera} className="tn-camrow">
              <span className="tn-camrow-name">{a.camera}</span>
              <span className="tn-camrow-detail">{a.detail}</span>
            </div>
          ))}
          {f.alerts.some((a) => a.ranked !== false) && (
            <div className="tn-note">
              {f.alerts.every((a) => a.ranked !== false)
                ? 'These are ranked on what they saw before they stopped.'
                : 'Those still in the plan are ranked on what they saw before they stopped.'}
            </div>
          )}
        </section>
      )}

      {shownAlerts.length > 0 && (
        <section className="card tn-card" aria-labelledby="tn-alerts-h">
          <h2 id="tn-alerts-h" className="sect">Alerts</h2>
          {shownAlerts.map((a, i) => {
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
                <div key={w.camera_id ?? w.camera} className="tn-where">
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
                          {cl.label} <span>{plural(visitsOf(cl), 'visit')}{cl.photos != null && ` (${plural(cl.photos, 'photo')})`}</span>
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              <div className="tn-note" style={{ marginTop: 4 }}>
                A visit is one arrival: photos of the same animal less than half an hour apart count once.
              </div>
            </div>
          )}

          {f.calibration?.statement && (
            <div className="block">
              <h2 className="sect">How often this has been right</h2>
              {f.calibration.lines && f.calibration.lines.length > 0
                ? <ul className="tn-record">{f.calibration.lines.map((line) => <li key={line}>{line}</li>)}</ul>
                : <div style={{ fontSize: 13, lineHeight: 1.5 }}>{f.calibration.statement}</div>}
            </div>
          )}

          {d && (
            <>
              <div className="block">
                <h2 className="sect">Photos by hour {bw && <span className="sect-note">tonight’s best hours in green</span>}</h2>
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
                <h2 className="sect">Photos by camera</h2>
                {d.by_camera.map((cam) => (
                  <div key={cam.id ?? cam.name} className="tn-hrow">
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
                  <h2 className="sect">Photos by animal</h2>
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
