import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  type Failure,
  type Got,
  type Me,
  ageLabel,
  api,
  fromEarlierNight,
  getFresh,
  nightOf,
  noAnswer,
  noAnswerWords,
  peek,
  peekMe,
  whoAmI,
} from '../api'
import HarvestPrompt from '../components/Harvest'
import SitPrompts from '../components/SitPrompts'
import { WindWeekLine, WindWeekStrip, judgedWind, useWindWeek, weekSaysWhy } from '../components/WindWeek'
import { useRefetchOnReturn } from '../hooks'
import { isCall, windColor, windFor, type WindReport } from '../map/geometry'
import { flushSits, isOn, onSitSync, saveSit, withPending } from '../sits'
import '../map/map.css'
import './stands.css'

type Stand = { id: string; name: string; lat: number | null; lon: number | null; claimed_tonight: boolean; claimed_by: string | null }
// `wind_at`: the moment the verdict saved at the reservation was for.
type Sit = { id: string; stand_id: string; night: string; user_id: string | null; outcome: string; started_at: string | null; ended_at: string | null; wind_status?: string | null; wind_text: string | null; claimed_at?: string | null; wind_at?: string | null }
const OUTCOMES = [['nothing', 'Saw nothing'], ['seen', 'Saw animals'], ['shootable_no_shot', 'Had a chance, no shot'], ['shot', 'Shot']] as const
const outcomeLabel = (value: string) => OUTCOMES.find(([key]) => key === value)?.[1] ?? 'Not reported'
// One short line per stand. The full sentence from the forecast sits behind "Wind details".
const WIND_LINE: Record<string, string> = {
  clean: 'Wind is right. Scent goes away from bedding.',
  scent_carries: 'Wind is wrong. Scent blows into bedding.',
  too_light: 'Wind too light to call.',
  no_wind_data: 'No wind forecast tonight.',
  no_bedding: 'No bedding drawn yet.',
  no_position: 'Not on the map yet.',
}

// The estate's clock, whatever the phone's is set to.
const estateClock = (iso: string) => new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' })
// When a wind line is for: tonight's sit (45 min after sunset), or now once dark.
// Only a call has a time: "Not on the map yet" is not a verdict for 20:39.
const windWhen = (w: WindReport) => { const at = windFor(w); return at && at[0].toUpperCase() + at.slice(1) }

// A write that never answers must not leave every button on "Reserving…".
const WRITE_TIMEOUT_MS = 20_000
// Start sit waits this long for the server, then opens Sit mode anyway: the start is
// saved on the phone and goes with the next signal, and the seat works without it.
const START_WAIT_MS = 4000

export default function Stands() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  // The last good list paints first, from this session or saved on the phone, and
  // the network replaces it. With no signal at the stand the page still opens on
  // the stands and your reservation, with its age (audit A-18, I-10).
  const [standsGot, setStandsGot] = useState<Got<Stand[]> | null>(() => peek<Stand[]>('/stands'))
  const [sitsGot, setSitsGot] = useState<Got<Sit[]> | null>(() => peek<Sit[]>('/sits'))
  // Tonight's wind at each stand and its week, in one call: the verdict at the sit
  // (as the map and Sit mode give it) and "Right wind for Charca: tonight 19–21 h,
  // Thu, Sat", with the hours behind the fold (feature 22).
  const wk = useWindWeek('/forecast/wind-week')
  // Who you are, as the phone last knew it, so your own stand reads "Yours
  // tonight" at once; /auth/me confirms it when it answers.
  const [me, setMe] = useState<Me | null>(peekMe)
  // True until this load's stands and sits have both answered (or given up).
  const [checking, setChecking] = useState(true)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const saving = useRef(false)
  const [filter, setFilter] = useState('all')
  const focused = useRef(false)
  const loaded = useRef(false)
  const ctl = useRef<AbortController | null>(null)
  // Re-render when a report waiting on the phone goes out, so "Saved on this phone" clears.
  const [, setSynced] = useState(0)

  function load() {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    const opts = { signal: c.signal, save: true }
    setErr('')
    setChecking(true)
    // Each on its own: who you are, the wind or the reservations failing must not
    // take the list of stands down with them. The wind asks for itself on opening.
    if (loaded.current) wk.reload()
    loaded.current = true
    whoAmI().then(setMe).catch(() => {})
    const sitsDone = getFresh<Sit[]>('/sits', opts).then(setSitsGot).catch(() => {})
    const standsDone = getFresh<Stand[]>('/stands', opts)
      .then(setStandsGot)
      .catch((e: Failure) => { if (!c.signal.aborted) setErr(`Couldn’t load stands. ${e.message}`) })
    Promise.all([sitsDone, standsDone]).then(() => { if (ctl.current === c) setChecking(false) })
  }
  useEffect(() => {
    load()
    // Reports saved on the phone go at the same time, not before: a queue waiting on
    // a thin link must not hold the list back (A-05). One sender for the whole app
    // (sits.ts), so this joins a send already under way instead of racing it.
    const off = onSitSync((r) => {
      setSynced((n) => n + 1)
      if (r.sent && !saving.current) getFresh<Sit[]>('/sits', { save: true }).then(setSitsGot).catch(() => {})
    })
    flushSits().then((r) => {
      // Counted by reports: a START or END SIT that went on its own is not a report.
      if (r.reports) setNotice(`${r.reports === 1 ? 'A sit report' : `${r.reports} sit reports`} saved on this phone went through.`)
      else if (r.sent) setNotice('Your sit was updated.')
    })
    return () => {
      off()
      ctl.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useRefetchOnReturn(() => { if (!saving.current) load() })

  // A saved copy from an earlier night knows the stands but not tonight's
  // reservations: those are dropped rather than shown as tonight's, whether the
  // copy is on screen because there is no signal or because the network hasn't
  // answered yet (the page paints its saved copy first).
  const tonightKey = nightOf(Date.now())
  const standsOld = !!standsGot && fromEarlierNight(standsGot.at)
  const stands = standsGot && standsGot.data.map((s) => (standsOld ? { ...s, claimed_tonight: false, claimed_by: null } : s))
  // /sits lists tonight's by default, and a sit still on from the night before (a
  // dawn sit after 06:00, A-20); each says its night, so a saved copy from an earlier
  // night drops out here. Each is shown as this phone knows it: with a report or
  // END SIT still waiting for signal.
  const sits = (sitsGot?.data ?? [])
    .map(withPending)
    .filter((s) => s.outcome !== 'cancelled' && (!s.night || s.night === tonightKey || isOn(s)))
  const reservationsUnknown = standsOld
  const staleGot = [standsGot, sitsGot].find((g) => g?.stale)
  // The copy on screen while the network is asked: how old it is, as Tonight says.
  const waitingOn = !staleGot && checking && standsGot && ageLabel(standsGot.at) !== 'just now' ? standsGot : null

  useEffect(() => {
    if (!stands || focused.current || !params.get('stand')) return
    document.getElementById(`stand-${params.get('stand')}`)?.scrollIntoView({ block: 'center' }); focused.current = true
  }, [stands, params])
  async function run(id: string, action: () => Promise<unknown>, message: string, next?: string) {
    if (saving.current) return
    saving.current = true; setBusy(id); setErr(''); setNotice('')
    try { const said = await action(); setNotice(typeof said === 'string' ? said : message); if (next) nav(next); else load() }
    catch (e) {
      setErr(noAnswer(e) === 'timeout' ? 'No answer from the server. It may have saved: check again in a moment.' : `That didn’t save. ${(e as Error).message}`)
    }
    finally { saving.current = false; setBusy(null) }
  }
  // Sit mode works with no signal: the start goes onto the phone and out with the
  // signal. Only a refusal (cancelled, not yours) keeps the hunter here.
  async function start(sitId: string) {
    const sent = saveSit(sitId, { start: true })
    const slow = await Promise.race([sent.then(() => false), new Promise<boolean>((done) => window.setTimeout(() => done(true), START_WAIT_MS))])
    if (slow) sent.catch(() => {})
  }
  // "What happened?" is the hunter saying so on purpose: it may lower what Sit mode
  // saved (a correction), and it waits on the phone with no signal.
  async function report(sitId: string, outcome: string) {
    const how = await saveSit(sitId, { outcome, correct: true })
    return how === 'queued' ? 'No signal. The report is saved on this phone and goes when there’s signal.' : undefined
  }
  const sitsAt = (id: string) => sits.filter(s => s.stand_id === id)
  // Your own sit first, the one on now before tonight's: a dawn sit still on and
  // tonight's reservation can share a stand.
  const sitFor = (id: string) => {
    const here = sitsAt(id), own = here.filter(s => !!me && s.user_id === me.id)
    return own.find(s => isOn(s)) ?? own[0] ?? here.find(s => s.night === tonightKey) ?? here[0]
  }
  const owned = (s: Stand) => !!me && (sitFor(s.id)?.user_id === me.id || s.claimed_by === me.id)
  // Tonight is the coming evening. A dawn sit from before 06:00, still on, doesn't
  // hold it: the stand can be reserved for the evening.
  const occupied = (s: Stand) => s.claimed_tonight || sitsAt(s.id).some(x => x.night === tonightKey)
  const yoursTonight = (s: Stand) => !!me && (s.claimed_by === me.id || sitsAt(s.id).some(x => x.night === tonightKey && x.user_id === me.id))
  // Somebody else is in it right now, from a dawn sit.
  const otherIn = (s: Stand) => !!me && sitsAt(s.id).some(x => x.night !== tonightKey && isOn(x) && x.user_id !== me.id)
  const shown = stands?.filter(s => filter === 'all' || (filter === 'mine' ? owned(s) : !occupied(s))) ?? []
  const free = stands?.filter(s => !occupied(s)) ?? []
  const yours = stands?.filter(owned) ?? []
  const reservedByYou = stands?.filter(yoursTonight) ?? []
  const stateOf = (sit: Sit | undefined, mine: boolean, taken: boolean) => {
    // An earlier night's copy can't say who has what tonight; "Free tonight" would be a guess.
    if (!mine && reservationsUnknown) return 'Tonight not known yet'
    // Until the phone knows who you are, a reserved stand may well be yours.
    if (!mine && taken && !me) return 'Reserved tonight'
    if (!mine) return taken ? 'Taken by another hunter' : 'Free tonight'
    const reported = !!sit && sit.outcome !== 'unreported'
    if (sit && isOn(sit)) return 'Your sit is on'
    if (sit?.ended_at && !reported) return 'Sit over. Nothing reported yet.'
    return reported ? `Reported: ${outcomeLabel(sit!.outcome).toLowerCase()}` : 'Yours tonight'
  }
  const canReserve = me?.role !== 'viewer'

  return <div className="stands-page estate-map">
    <div className="map-page-heading"><div><h1>Stands</h1><p>Who’s sitting where tonight.</p></div><Link className="map-button" to="/map">Map ↗</Link></div>
    {staleGot && <p className="stand-fresh" role="status">
      {noAnswerWords(staleGot.why)} Stands from {ageLabel(staleGot.at)}.{reservationsUnknown ? ' Tonight’s reservations will show when the signal is back.' : ' Reservations may have changed since.'}
      <button onClick={load} disabled={!!busy}>Try again</button>
    </p>}
    {waitingOn && <p className="stand-fresh stand-fresh--checking" role="status">
      Stands from {ageLabel(waitingOn.at)}. Checking…{reservationsUnknown && ' Tonight’s reservations aren’t known yet.'}
    </p>}
    {err && <div className="map-message map-message--error" role="alert">{err}<button onClick={load} disabled={!!busy}>Try again</button></div>}
    {notice && <div className="map-message" role="status">{notice}</div>}
    <SitPrompts page="stands" />
    <HarvestPrompt />
    {!stands && !err && <div className="status-panel" role="status">Loading stands…</div>}
    {stands && stands.length > 0 && !reservationsUnknown && <>
      <p className="stand-tonight" aria-label="Tonight's reservations">
        {free.length === 0 ? 'Every stand is taken tonight.' : free.length === stands.length ? 'Every stand is free tonight.' : `${free.length} of ${stands.length} stands free tonight.`}
        {reservedByYou.length > 0 && ` You have ${reservedByYou.map(s => s.name).join(' and ')}.`}
      </p>
      <div className="stand-filters" aria-label="Filter stands">{[['all', `All · ${stands.length}`], ['available', `Free · ${free.length}`], ['mine', `Yours · ${yours.length}`]].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
    </>}
    {stands?.length === 0 && <div className="stand-empty"><h2>No stands yet</h2><p>Add the seats you actually sit in on the map. They show up here to reserve.</p><Link className="map-button map-button--primary" to="/map">{me?.role === 'admin' ? 'Add a stand on the map →' : 'Open the map →'}</Link></div>}
    {stands && stands.length > 0 && shown.length === 0 && <p className="status-panel">{filter === 'mine' ? 'You haven’t reserved a stand tonight.' : 'No stands free tonight.'}</p>}
    {shown.map(s => {
      const sit = sitFor(s.id), mine = owned(s), taken = occupied(s)
      // In the stand now: "Back to sit" until END SIT, whatever was reported (A-06).
      const on = !!sit && isOn(sit), fresh = !!sit && !sit.started_at && sit.outcome === 'unreported'
      // Ended with nothing said: ask, instead of hiding the question behind a fold.
      const ask = !!sit?.ended_at && sit.outcome === 'unreported'
      const week = wk.week?.stands.find((x) => x.stand_id === s.id)
      const wind = week?.tonight as WindReport | undefined
      // A stand that can't be judged, or a week with no forecast, says why once, in the
      // week's line: "Not on the map yet." over "Loma isn't on the map yet, so…" said it twice.
      const windLine = wind && week && !(weekSaysWhy(week) && !judgedWind(wind.status)) ? WIND_LINE[wind.status] ?? null : null
      // A copy kept with no signal says how old it is.
      const windAge = wk.got?.stale ? `from ${ageLabel(wk.got.at)}` : ''
      // In your dawn sit, Back to sit comes first; reserving the evening is the lesser thing.
      const later = mine && on
      const reserve = !taken && !reservationsUnknown && canReserve && <button className={`map-button${later ? ' stand-reserve-later' : ' map-button--primary'}`} disabled={!!busy} onClick={() => run(s.id, () => api('/sits', { method: 'POST', body: JSON.stringify({ stand_id: s.id }), timeoutMs: WRITE_TIMEOUT_MS }), `${s.name} is yours tonight.`)}>{busy === s.id ? 'Reserving…' : later ? 'Reserve for tonight' : 'Reserve'}</button>
      return <article key={s.id} id={`stand-${s.id}`} className={`stand-entry${params.get('stand') === s.id ? ' stand-entry--selected' : ''}`}>
        <div className="stand-entry-top"><div><h2>{s.name}</h2><span className={`stand-state${mine ? ' stand-state--mine' : ''}`}>{stateOf(sit, mine, taken)}</span></div><Link className="map-link" to={`/map?stand=${s.id}`}>{s.lat == null || s.lon == null ? 'Place on map ↗' : 'Map ↗'}</Link></div>
        {/* Held open from the first paint, so the wind arriving doesn't move Reserve
            under a thumb (audit I-08). */}
        <div className="stand-wind-slot">
          {week ? <>
            {windLine && <p className="stand-wind-line" style={{ color: windColor(wind!.status) }}>{windLine}{(windWhen(wind!) || windAge) && <span className="stand-wind-for">{[windWhen(wind!), windAge].filter(Boolean).join(', ')}</span>}</p>}
            <WindWeekLine stand={week} />
          </> : <p className="stand-wind-wait">{wk.wait}</p>}
        </div>
        {otherIn(s) && <p className="stand-now">Another hunter is in it now, from a dawn sit.</p>}
        {!later && reserve}
        {mine && sit && <>
          {(on || fresh) && <div className="map-actions"><button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => (on ? Promise.resolve() : start(sit.id)), '', `/sit/${sit.id}`)}>{busy === s.id ? 'Saving…' : on ? 'Back to sit' : 'Start sit'}</button>{fresh && <button className="map-link" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: 'cancelled', at: new Date().toISOString() }), timeoutMs: WRITE_TIMEOUT_MS }), 'Reservation cancelled.')}>Cancel</button>}</div>}
          {sit.unsent && <p className="stand-unsent">Saved on this phone. It goes when there’s signal.</p>}
          {later && reserve}
          <details className="stand-outcome" open={ask || undefined}><summary>What happened?</summary><div className="stand-outcome-buttons">{OUTCOMES.map(([value, label]) => <button key={value} className="map-button" aria-pressed={sit.outcome === value} disabled={!!busy} onClick={() => run(s.id, () => report(sit.id, value), 'Sit report saved.')}>{label}</button>)}</div></details>
        </>}
        <details className="stand-wind"><summary>Wind hour by hour</summary>
          {wk.week && week ? <WindWeekStrip week={wk.week} stand={week} /> : <p className="ww-note">{wk.wait}</p>}
          {wind?.text && <p>{wind.text}</p>}
          {mine && sit?.wind_text && <p><span className="stand-wind-when">When you reserved{sit.claimed_at ? ` at ${estateClock(sit.claimed_at)}` : ''}{sit.wind_at && isCall(sit.wind_status) ? `, for ${estateClock(sit.wind_at)}` : ''}</span>{sit.wind_text}</p>}
          <Link to={`/map?stand=${s.id}`}>See it on the map →</Link>
        </details>
      </article>
    })}
    {!!stands?.length && <p className="stand-footnote">Reservations are for tonight only.</p>}
  </div>
}
