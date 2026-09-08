import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { flushSitQueue } from './SitMode'
import '../map/map.css'

type Stand = { id: string; name: string; lat: number | null; lon: number | null; claimed_tonight: boolean; claimed_by: string | null }
type Sit = { id: string; stand_id: string; user_id: string | null; outcome: string; started_at: string | null; wind_text: string | null }
type Me = { id: string; role: string }
const OUTCOMES = [['nothing', 'No animals seen'], ['seen', 'Animals seen'], ['shootable_no_shot', 'Opportunity, no shot'], ['shot', 'Shot taken']] as const
const outcomeLabel = (value: string) => OUTCOMES.find(([key]) => key === value)?.[1] ?? 'Outcome not recorded'

export default function Stands() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const [stands, setStands] = useState<Stand[] | null>(null)
  const [sits, setSits] = useState<Sit[]>([])
  const [me, setMe] = useState<Me | null>(null)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const saving = useRef(false)
  const [filter, setFilter] = useState('all')
  const focused = useRef(false)
  async function load() {
    setErr('')
    try {
      const [all, reports, user] = await Promise.all([api<Stand[]>('/stands'), api<Sit[]>('/sits'), api<Me>('/users/me')])
      setStands(all); setSits(reports.filter(s => s.outcome !== 'cancelled')); setMe(user)
    } catch (e) { setErr(`Could not load stands. ${(e as Error).message}`) }
  }
  useEffect(() => {
    flushSitQueue().then(n => { if (n) setNotice(`${n} offline sit report${n === 1 ? '' : 's'} synced.`) }).catch(() => setNotice('Some offline reports could not sync. They remain saved on this device.')).finally(load)
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
    catch (e) { setErr(`Could not save your change. ${(e as Error).message}`) }
    finally { saving.current = false; setBusy(null) }
  }
  const sitFor = (id: string) => sits.find(s => s.stand_id === id)
  const owned = (s: Stand) => !!me && (sitFor(s.id)?.user_id === me.id || s.claimed_by === me.id)
  const occupied = (s: Stand) => s.claimed_tonight || !!sitFor(s.id)
  const shown = stands?.filter(s => filter === 'all' || (filter === 'mine' ? owned(s) : !occupied(s))) ?? []

  return <div className="stands-page estate-map">
    <div className="map-page-heading"><div><h1>Tonight’s stands</h1><p>Choose a position. Reserve it. Record your sit.</p></div><Link className="map-button" to="/map">Open map ↗</Link></div>
    {err && <div className="map-message map-message--error" role="alert">{err}<button onClick={load} disabled={!!busy}>Retry loading stands</button></div>}
    {notice && <div className="map-message" role="status">{notice}</div>}
    {!stands && !err && <div className="status-panel" role="status">Loading stands…</div>}
    {stands && stands.length > 0 && <>
      <div className="stand-summary" aria-label="Tonight's reservations"><div><strong>{stands.filter(s => !occupied(s)).length}</strong><span>Available</span></div><div><strong>{stands.filter(owned).length}</strong><span>Reserved by you</span></div><div><strong>{stands.filter(s => occupied(s) && !owned(s)).length}</strong><span>Reserved by others</span></div></div>
      <div className="stand-filters" aria-label="Filter stands">{[['all', 'All stands'], ['available', 'Available'], ['mine', 'Your reservations']].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}</div>
    </>}
    {stands?.length === 0 && <div className="stand-empty"><h2>No stands yet</h2><p>Add the positions where you actually sit on the estate map. They’ll appear here for reservations and sit reports.</p><Link className="map-button map-button--primary" to="/map">{me?.role === 'admin' ? 'Add a stand on the map →' : 'View estate map →'}</Link></div>}
    {stands && stands.length > 0 && shown.length === 0 && <p className="status-panel">No stands match this filter. Choose All stands to see every location.</p>}
    {shown.map(s => {
      const sit = sitFor(s.id), mine = owned(s), taken = occupied(s), active = sit?.outcome === 'unreported'
      return <article key={s.id} id={`stand-${s.id}`} className={`stand-entry${params.get('stand') === s.id ? ' stand-entry--selected' : ''}`}>
        <div className="stand-entry-top"><div><span className={`stand-state${mine ? ' stand-state--mine' : ''}`}>{mine ? active ? sit?.started_at ? 'Your sit is in progress' : 'Reserved by you' : 'Your sit is recorded' : taken ? 'Reserved by another hunter' : 'Available tonight'}</span><h2>{s.name}</h2></div><Link className="map-link" to={`/map?stand=${s.id}`}>{s.lat == null || s.lon == null ? 'Set map position ↗' : 'View on map ↗'}</Link></div>
        {mine && sit?.wind_text ? <details className="stand-wind"><summary>Wind check saved with your reservation</summary><p>{sit.wind_text}</p><Link to={`/map?stand=${s.id}`}>Check current conditions on the map →</Link></details> : <p className="map-detail-copy">{taken ? 'This position is already reserved tonight.' : 'Check wind direction and nearby bedding on the map before reserving.'}</p>}
        {!taken && <button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => api('/sits', { method: 'POST', body: JSON.stringify({ stand_id: s.id }) }), `${s.name} reserved for tonight.`)}>{busy === s.id ? 'Reserving…' : 'Reserve for tonight'}</button>}
        {mine && sit && active && <>
          <div className="map-actions"><button className="map-button map-button--primary" disabled={!!busy} onClick={() => run(s.id, () => sit.started_at ? Promise.resolve() : api(`/sits/${sit.id}/start`, { method: 'POST' }), '', `/sit/${sit.id}`)}>{busy === s.id ? 'Saving…' : sit.started_at ? 'Continue sit →' : 'Start sit →'}</button>{!sit.started_at && <button className="map-link" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: 'cancelled' }) }), 'Reservation cancelled. The stand is available again.')}>Cancel reservation</button>}</div>
          <details className="stand-outcome"><summary>Record sit outcome</summary><p>Choose what happened during your sit. This closes the report.</p><div className="stand-outcome-buttons">{OUTCOMES.map(([value, label]) => <button key={value} className="map-button" disabled={!!busy} onClick={() => run(s.id, () => api(`/sits/${sit.id}`, { method: 'PATCH', body: JSON.stringify({ outcome: value }) }), 'Sit outcome saved.')}>{label}</button>)}</div></details>
        </>}
        {mine && sit && !active && <p className="stand-recorded">{outcomeLabel(sit.outcome)}</p>}
      </article>
    })}
    {!!stands?.length && <p className="stand-footnote">Reservations are for tonight. An unreported sit is kept separate from a sit with no animals seen. Manage stand positions on the map.</p>}
  </div>
}
