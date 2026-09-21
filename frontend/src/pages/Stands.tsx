import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { windColor, type MapData, type WindReport } from '../map/geometry'
import { flushSitQueue } from './SitMode'
import '../map/map.css'
import './stands.css'

type Stand = { id: string; name: string; lat: number | null; lon: number | null; claimed_tonight: boolean; claimed_by: string | null }
type Sit = { id: string; stand_id: string; user_id: string | null; outcome: string; started_at: string | null; wind_text: string | null }
type Me = { id: string; role: string }
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

export default function Stands() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [stands, setStands] = useState<Stand[] | null>(null)
  const [sits, setSits] = useState<Sit[]>([])
  const [winds, setWinds] = useState<Record<string, WindReport>>({})
  const [me, setMe] = useState<Me | null>(null)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const saving = useRef(false)
  const [filter, setFilter] = useState('all')
  const focused = useRef(false)
  async function load() {
    setErr('')
    // Wind is a bonus. If it fails the list still loads.
    api<MapData>('/map/tonight').then(d => setWinds(Object.fromEntries(d.stands.map(s => [s.id, s.wind])))).catch(() => {})
    try {
      const [all, reports, user] = await Promise.all([api<Stand[]>('/stands'), api<Sit[]>('/sits'), api<Me>('/auth/me')])
      setStands(all); setSits(reports.filter(s => s.outcome !== 'cancelled')); setMe(user)
    } catch (e) { setErr(`Couldn’t load stands. ${(e as Error).message}`) }
  }
  useEffect(() => {
    flushSitQueue().then(n => { if (n) setNotice(`${n} sit report${n === 1 ? '' : 's'} sent.`) }).catch(() => setNotice('Some sit reports couldn’t send. They’re still saved on this phone.')).finally(load)
  }, [])
  useRefetchOnReturn(() => { if (!saving.current) load() })
  useEffect(() => {
    if (!stands || focused.current || !params.get('stand')) return
    document.getElementById(`stand-${params.get('stand')}`)?.scrollIntoView({ block: 'center' }); focused.current = true
  }, [stands, params])
  async function run(id: string, action: () => Promise<unknown>, message: string, next?: string) {
    if (saving.current) return
    saving.current = true; setBusy(id); setErr(''); setNotice('')
    try { await action(); setNotice(message); if (next) nav(next); else await load() }
    catch (e) { setErr(`That didn’t save. ${(e as Error).message}`) }
    finally { saving.current = false; setBusy(null) }
  }
  const sitFor = (id: string) => sits.find(s => s.stand_id === id)
  const owned = (s: Stand) => !!me && (sitFor(s.id)?.user_id === me.id || s.claimed_by === me.id)
  const occupied = (s: Stand) => s.claimed_tonight || !!sitFor(s.id)
  const shown = stands?.filter(s => filter === 'all' || (filter === 'mine' ? owned(s) : !occupied(s))) ?? []
  const free = stands?.filter(s => !occupied(s)) ?? []
  const yours = stands?.filter(owned) ?? []
  const stateOf = (sit: Sit | undefined, mine: boolean, taken: boolean, active: boolean) => {
    if (!mine) return taken ? 'Taken by another hunter' : 'Free tonight'
    if (!active) return `Reported: ${outcomeLabel(sit?.outcome ?? '').toLowerCase()}`
    return sit?.started_at ? 'Your sit is on' : 'Yours tonight'
  }

  return <div className="stands-page estate-map">
    <div className="map-page-heading"><div><h1>Stands</h1><p>Who’s sitting where tonight.</p></div><Link className="map-button" to="/map">Map ↗</Link></div>
    {err && <div className="map-message map-message--error" role="alert">{err}<button onClick={load} disabled={!!busy}>Try again</button></div>}
    {notice && <div className="map-message" role="status">{notice}</div>}
    {!stands && !err && <div className="status-panel" role="status">Loading stands…</div>}
    {stands && stands.length > 0 && <>
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
        {!taken && <button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => api('/sits', { method: 'POST', body: JSON.stringify({ stand_id: s.id }) }), `${s.name} is yours tonight.`)}>{busy === s.id ? 'Reserving…' : 'Reserve'}</button>}
        {mine && sit && active && <>
          <div className="map-actions"><button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => sit.started_at ? Promise.resolve() : api(`/sits/${sit.id}/start`, { method: 'POST' }), '', `/sit/${sit.id}`)}>{busy === s.id ? 'Saving…' : sit.started_at ? 'Back to sit' : 'Start sit'}</button>{!sit.started_at && <button className="map-link" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: 'cancelled' }) }), 'Reservation cancelled.')}>Cancel</button>}</div>
          <details className="stand-outcome"><summary>What happened?</summary><div className="stand-outcome-buttons">{OUTCOMES.map(([value, label]) => <button key={value} className="map-button" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: value }) }), 'Sit report saved.')}>{label}</button>)}</div></details>
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
