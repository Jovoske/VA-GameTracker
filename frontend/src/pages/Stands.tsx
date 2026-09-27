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
import { useRefetchOnReturn } from '../hooks'
import { windColor, type MapData, type WindReport } from '../map/geometry'
import { flushSitQueue } from './SitMode'
import '../map/map.css'
import './stands.css'

type Stand = { id: string; name: string; lat: number | null; lon: number | null; claimed_tonight: boolean; claimed_by: string | null }
type Sit = { id: string; stand_id: string; night: string; user_id: string | null; outcome: string; started_at: string | null; wind_text: string | null }
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

// A write that never answers must not leave every button on "Reserving…".
const WRITE_TIMEOUT_MS = 20_000

export default function Stands() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  // The last good list paints first, from this session or saved on the phone, and
  // the network replaces it. With no signal at the stand the page still opens on
  // the stands and your reservation, with its age (audit A-18, I-10).
  const [standsGot, setStandsGot] = useState<Got<Stand[]> | null>(() => peek<Stand[]>('/stands'))
  const [sitsGot, setSitsGot] = useState<Got<Sit[]> | null>(() => peek<Sit[]>('/sits'))
  const [winds, setWinds] = useState<Record<string, WindReport>>({})
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
  const ctl = useRef<AbortController | null>(null)

  function load() {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    const opts = { signal: c.signal, save: true }
    setErr('')
    setChecking(true)
    // Each on its own: who you are, the wind or the reservations failing must not
    // take the list of stands down with them.
    getFresh<MapData>('/map/tonight', { signal: c.signal })
      .then((got) => { if (!got.stale) setWinds(Object.fromEntries(got.data.stands.map((s) => [s.id, s.wind]))) })
      .catch(() => {})
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
    // a thin link must not hold the list back (A-05).
    flushSitQueue()
      .then((n) => {
        if (!n) return
        setNotice(`${n} sit report${n === 1 ? '' : 's'} sent.`)
        getFresh<Sit[]>('/sits', { save: true }).then(setSitsGot).catch(() => {})
      })
      .catch(() => setNotice('Some sit reports couldn’t send. They’re still saved on this phone.'))
    return () => ctl.current?.abort()
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
  // /sits lists tonight's by default; each says its night, so a saved copy from an
  // earlier one drops out here.
  const sits = (sitsGot?.data ?? []).filter((s) => s.outcome !== 'cancelled' && (!s.night || s.night === tonightKey))
  const reservationsUnknown = standsOld
  const staleGot = [standsGot, sitsGot].find((g) => g?.stale)
  // The copy on screen while the network is asked: how old it is, as Tonight says.
  const waitingOn = !staleGot && checking && standsGot && ageLabel(standsGot.at) !== 'just now' ? standsGot : null

  useEffect(() => {
    if (!stands || focused.current || !params.get('stand')) return
    document.getElementById(`stand-${params.get('stand')}`)?.scrollIntoView({ block: 'center' }); focused.current = true
  }, [stands, params])
  async function run(id: string, action: () => Promise<unknown>, message: string, next?: string, goAnyway = false) {
    if (saving.current) return
    saving.current = true; setBusy(id); setErr(''); setNotice('')
    try { await action(); setNotice(message); if (next) nav(next); else load() }
    catch (e) {
      // Sit mode works with no signal (reports wait on the phone), so a start that
      // can't reach the server still opens it.
      if (next && goAnyway && noAnswer(e)) nav(next)
      else setErr(noAnswer(e) === 'timeout' ? 'No answer from the server. It may have saved: check again in a moment.' : `That didn’t save. ${(e as Error).message}`)
    }
    finally { saving.current = false; setBusy(null) }
  }
  const sitFor = (id: string) => sits.find(s => s.stand_id === id)
  const owned = (s: Stand) => !!me && (sitFor(s.id)?.user_id === me.id || s.claimed_by === me.id)
  const occupied = (s: Stand) => s.claimed_tonight || !!sitFor(s.id)
  const shown = stands?.filter(s => filter === 'all' || (filter === 'mine' ? owned(s) : !occupied(s))) ?? []
  const free = stands?.filter(s => !occupied(s)) ?? []
  const yours = stands?.filter(owned) ?? []
  const stateOf = (sit: Sit | undefined, mine: boolean, taken: boolean, active: boolean) => {
    // An earlier night's copy can't say who has what tonight; "Free tonight" would be a guess.
    if (!mine && reservationsUnknown) return 'Tonight not known yet'
    // Until the phone knows who you are, a reserved stand may well be yours.
    if (!mine && taken && !me) return 'Reserved tonight'
    if (!mine) return taken ? 'Taken by another hunter' : 'Free tonight'
    if (!active) return `Reported: ${outcomeLabel(sit?.outcome ?? '').toLowerCase()}`
    return sit?.started_at ? 'Your sit is on' : 'Yours tonight'
  }

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
    {!stands && !err && <div className="status-panel" role="status">Loading stands…</div>}
    {stands && stands.length > 0 && !reservationsUnknown && <>
      <p className="stand-tonight" aria-label="Tonight's reservations">
        {free.length === 0 ? 'Every stand is taken tonight.' : free.length === stands.length ? 'Every stand is free tonight.' : `${free.length} of ${stands.length} stands free tonight.`}
        {yours.length > 0 && ` You have ${yours.map(s => s.name).join(' and ')}.`}
      </p>
      <div className="stand-filters" aria-label="Filter stands">{[['all', `All · ${stands.length}`], ['available', `Free · ${free.length}`], ['mine', `Yours · ${yours.length}`]].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
    </>}
    {stands?.length === 0 && <div className="stand-empty"><h2>No stands yet</h2><p>Add the seats you actually sit in on the map. They show up here to reserve.</p><Link className="map-button map-button--primary" to="/map">{me?.role === 'admin' ? 'Add a stand on the map →' : 'Open the map →'}</Link></div>}
    {stands && stands.length > 0 && shown.length === 0 && <p className="status-panel">{filter === 'mine' ? 'You haven’t reserved a stand tonight.' : 'No stands free tonight.'}</p>}
    {shown.map(s => {
      const sit = sitFor(s.id), mine = owned(s), taken = occupied(s), active = sit?.outcome === 'unreported'
      const wind = winds[s.id]
      const windLine = wind ? WIND_LINE[wind.status] ?? null : null
      const hasDetails = !!(wind?.text || (mine && sit?.wind_text))
      return <article key={s.id} id={`stand-${s.id}`} className={`stand-entry${params.get('stand') === s.id ? ' stand-entry--selected' : ''}`}>
        <div className="stand-entry-top"><div><h2>{s.name}</h2><span className={`stand-state${mine ? ' stand-state--mine' : ''}`}>{stateOf(sit, mine, taken, active)}</span></div><Link className="map-link" to={`/map?stand=${s.id}`}>{s.lat == null || s.lon == null ? 'Place on map ↗' : 'Map ↗'}</Link></div>
        {windLine && <p className="stand-wind-line" style={{ color: windColor(wind!.status) }}>{windLine}</p>}
        {!taken && !reservationsUnknown && <button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => api('/sits', { method: 'POST', body: JSON.stringify({ stand_id: s.id }), timeoutMs: WRITE_TIMEOUT_MS }), `${s.name} is yours tonight.`)}>{busy === s.id ? 'Reserving…' : 'Reserve'}</button>}
        {mine && sit && active && <>
          <div className="map-actions"><button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => sit.started_at ? Promise.resolve() : api(`/sits/${sit.id}/start`, { method: 'POST', timeoutMs: WRITE_TIMEOUT_MS }), '', `/sit/${sit.id}`, true)}>{busy === s.id ? 'Saving…' : sit.started_at ? 'Back to sit' : 'Start sit'}</button>{!sit.started_at && <button className="map-link" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: 'cancelled' }), timeoutMs: WRITE_TIMEOUT_MS }), 'Reservation cancelled.')}>Cancel</button>}</div>
          <details className="stand-outcome"><summary>What happened?</summary><div className="stand-outcome-buttons">{OUTCOMES.map(([value, label]) => <button key={value} className="map-button" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: value }), timeoutMs: WRITE_TIMEOUT_MS }), 'Sit report saved.')}>{label}</button>)}</div></details>
        </>}
        {hasDetails && <details className="stand-wind"><summary>Wind details</summary>
          {wind?.text && <p>{wind.text}</p>}
          {mine && sit?.wind_text && <p><span className="stand-wind-when">When you reserved</span>{sit.wind_text}</p>}
          <Link to={`/map?stand=${s.id}`}>See it on the map →</Link>
        </details>}
      </article>
    })}
    {!!stands?.length && <p className="stand-footnote">Reservations are for tonight only.</p>}
  </div>
}
