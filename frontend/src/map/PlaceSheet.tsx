import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { validLngLat, windColor, windGeometry, type MapStand, type Zone } from './geometry'

// One short verdict per stand. The forecast's own sentence follows it.
const WIND_HEAD: Record<string, string> = {
  clean: 'Wind is right. Scent goes away from bedding.',
  scent_carries: 'Wind is wrong. Scent blows into bedding.',
  too_light: 'Wind too light to call.',
  no_wind_data: 'No wind forecast tonight.',
  no_bedding: 'No bedding drawn yet.',
  no_position: 'Not on the map yet.',
}

/** An error that appears inside the sheet scrolls itself into view, so it is never below the fold. */
export function InlineError({ text }: { text: string }) {
  const el = useRef<HTMLParagraphElement>(null)
  useEffect(() => { el.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) }, [text])
  return <p ref={el} className="map-inline-error" role="alert">{text}</p>
}

function Heading({ kind, name, children }: { kind: string; name: string; children?: React.ReactNode }) {
  return <>
    <span className="map-eyebrow">{kind}</span>
    <h2 className="bsheet-name">{name}</h2>
    {children}
  </>
}

export function StandHeader({ stand }: { stand: MapStand }) {
  const status = validLngLat(stand.lon, stand.lat) ? stand.wind.status : 'no_position'
  return <Heading kind="Stand" name={stand.name}>
    <p className="bsheet-verdict" style={{ color: windColor(status) }}>{WIND_HEAD[status] ?? 'Wind unknown.'}</p>
  </Heading>
}
export function ZoneHeader({ zone }: { zone: Zone }) {
  return <Heading kind="Bedding" name={zone.name}><p className="bsheet-meta">Where the animals lie up.</p></Heading>
}

/**
 * Remove, asked for twice, with any error shown right here next to the button that
 * failed and a Try again that repeats that same remove (B-11).
 */
function RemoveControl({ name, onRemove }: { name: string; onRemove: () => Promise<void> }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  // A refusal (sit history) won't change on a retry, so it gets no Try again.
  const [final, setFinal] = useState(false)
  async function run() {
    setBusy(true); setErr(''); setFinal(false)
    try { await onRemove() } catch (e) { setErr((e as Error).message); setFinal(!!(e as Error & { final?: boolean }).final) } finally { setBusy(false) }
  }
  if (!asking) return <button type="button" className="map-link" onClick={() => setAsking(true)}>Remove…</button>
  return <div className="map-confirm" role="group" aria-label={`Remove ${name}`}>
    <p>Remove {name} from the map?</p>
    <div className="map-actions">
      {!final && <button type="button" className="map-button" disabled={busy} onClick={run}>{busy ? 'Removing…' : err ? 'Try again' : 'Remove'}</button>}
      <button type="button" className="map-button" disabled={busy} onClick={() => { setAsking(false); setErr(''); setFinal(false) }}>{final ? 'OK' : 'Keep'}</button>
    </div>
    {err && <InlineError text={err} />}
  </div>
}

export function RenameControl({ name, onRename, maxLength = 80 }: { name: string; onRename: (name: string) => Promise<void>; maxLength?: number }) {
  const [value, setValue] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (value == null) return <button type="button" className="map-button" onClick={() => setValue(name)}>Rename</button>
  async function save() {
    if (!value?.trim() || busy) return
    setBusy(true); setErr('')
    try { await onRename(value.trim()); setValue(null) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return <form className="map-rename" onSubmit={e => { e.preventDefault(); save() }}>
    <label className="map-field">New name<input maxLength={maxLength} value={value} disabled={busy} onChange={e => setValue(e.target.value)} /></label>
    <div className="map-actions"><button className="map-button map-button--primary" disabled={busy || !value.trim()}>{busy ? 'Saving…' : err ? 'Try again' : 'Save name'}</button><button type="button" className="map-button" disabled={busy} onClick={() => { setValue(null); setErr('') }}>Cancel</button></div>
    {err && <InlineError text={err} />}
  </form>
}

export function StandBody({ stand, scentRange, admin, onMove, onRemove, onRename }: {
  stand: MapStand
  scentRange: number
  admin: boolean
  onMove: () => void
  onRemove: () => Promise<void>
  onRename: (name: string) => Promise<void>
}) {
  const placed = validLngLat(stand.lon, stand.lat)
  const drawn = !!windGeometry(stand, scentRange)
  return <>
    {/* An unplaced stand has no wind to give: the header already says it isn't on the map. */}
    {placed && <p className="map-detail-copy">{stand.wind.text}</p>}
    {placed && stand.wind.source && stand.wind.source !== 'synoptic' && stand.wind.source !== 'unknown' && <p className="map-detail-copy">That’s the slope air at this seat, not the forecast wind above.</p>}
    {drawn && <p className="map-caveat">The cone shows how far scent carries tonight. An indication only: wind near the ground swirls.</p>}
    {!placed && !admin && <p className="map-detail-copy">An admin can place it.</p>}
    <Link className="map-button map-button--primary map-button--big" to={`/stands?stand=${stand.id}`}>Reserve this stand</Link>
    {admin && <div className="map-actions map-actions--admin">
      <button type="button" className="map-button" onClick={onMove}>{placed ? 'Move' : 'Place it on the map'}</button>
      <RenameControl name={stand.name} onRename={onRename} />
      <RemoveControl name={stand.name} onRemove={onRemove} />
    </div>}
  </>
}

export function ZoneBody({ zone, admin, onRemove, onRename, onRedraw }: {
  zone: Zone
  admin: boolean
  onRemove: () => Promise<void>
  onRename: (name: string) => Promise<void>
  /** Draw the outline again, keeping its name and its place in the wind calls (B-22). */
  onRedraw: () => void
}) {
  return <>
    <p className="map-detail-copy">Every wind call on this map is about keeping scent out of here.</p>
    {admin && <div className="map-actions map-actions--admin">
      <button type="button" className="map-button" onClick={onRedraw}>Redraw outline</button>
      <RenameControl name={zone.name} onRename={onRename} />
      <RemoveControl name={zone.name} onRemove={onRemove} />
    </div>}
  </>
}

/**
 * For a camera placed by hand that also reports a position of its own: say that the
 * hand placement holds, and offer the camera's own back (B-09, E-16).
 */
export function OwnGpsControl({ onUse }: { onUse: () => Promise<void> }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  async function run() {
    setBusy(true); setErr('')
    try { await onUse() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return <div className="map-own-gps">
    <p className="map-detail-copy">Placed by hand, so the camera’s own GPS doesn’t move it.</p>
    <button type="button" className="map-button" disabled={busy} onClick={run}>{busy ? 'Saving…' : err ? 'Try again' : 'Use the camera’s own GPS position'}</button>
    {err && <InlineError text={err} />}
  </div>
}
