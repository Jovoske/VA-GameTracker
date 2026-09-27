import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { cap, t, tOr } from '../i18n'
import { validLngLat, windColor, windFor, windGeometry, type MapStand, type Zone } from './geometry'

// One short verdict per stand (the same lines as Stands). The forecast's own sentence follows it.
const windHead = (status: string) => tOr(`standWind.${status}`, t('place.windUnknown'))

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
  // The time the call is for, as on Stands and in Sit mode: "For 20:39", "Now".
  const at = windFor(stand.wind, status)
  return <Heading kind={t('map.stand')} name={stand.name}>
    <p className="bsheet-verdict" style={{ color: windColor(status) }}>{windHead(status)}</p>
    {at && <p className="bsheet-meta">{cap(at)}</p>}
  </Heading>
}
export function ZoneHeader({ zone }: { zone: Zone }) {
  return <Heading kind={t('msheet.bedding')} name={zone.name}><p className="bsheet-meta">{t('msheet.beddingNote')}</p></Heading>
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
  if (!asking) return <button type="button" className="map-link" onClick={() => setAsking(true)}>{t('place.removeDots')}</button>
  return <div className="map-confirm" role="group" aria-label={t('admin.removeNamed', { name })}>
    <p>{t('place.removeFromMap', { name })}</p>
    <div className="map-actions">
      {!final && <button type="button" className="map-button" disabled={busy} onClick={run}>{busy ? t('common.removing') : err ? t('common.tryAgain') : t('common.remove')}</button>}
      <button type="button" className="map-button" disabled={busy} onClick={() => { setAsking(false); setErr(''); setFinal(false) }}>{final ? t('common.ok') : t('common.keep')}</button>
    </div>
    {err && <InlineError text={err} />}
  </div>
}

export function RenameControl({ name, onRename, maxLength = 80 }: { name: string; onRename: (name: string) => Promise<void>; maxLength?: number }) {
  const [value, setValue] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (value == null) return <button type="button" className="map-button" onClick={() => setValue(name)}>{t('cameras.rename')}</button>
  async function save() {
    if (!value?.trim() || busy) return
    setBusy(true); setErr('')
    try { await onRename(value.trim()); setValue(null) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return <form className="map-rename" onSubmit={e => { e.preventDefault(); save() }}>
    <label className="map-field">{t('place.newName')}<input maxLength={maxLength} value={value} disabled={busy} onChange={e => setValue(e.target.value)} /></label>
    <div className="map-actions"><button className="map-button map-button--primary" disabled={busy || !value.trim()}>{busy ? t('common.saving') : err ? t('common.tryAgain') : t('place.saveName')}</button><button type="button" className="map-button" disabled={busy} onClick={() => { setValue(null); setErr('') }}>{t('common.cancel')}</button></div>
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
    {placed && stand.wind.source && stand.wind.source !== 'synoptic' && stand.wind.source !== 'unknown' && <p className="map-detail-copy">{t('place.slopeAir')}</p>}
    {drawn && <p className="map-caveat">{t('place.cone')}</p>}
    {!placed && !admin && <p className="map-detail-copy">{t('place.adminCan')}</p>}
    <Link className="map-button map-button--primary map-button--big" to={`/stands?stand=${stand.id}`}>{t('place.reserve')}</Link>
    {admin && <div className="map-actions map-actions--admin">
      <button type="button" className="map-button" onClick={onMove}>{placed ? t('place.move') : t('place.placeIt')}</button>
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
    <p className="map-detail-copy">{t('place.everyCall')}</p>
    {admin && <div className="map-actions map-actions--admin">
      <button type="button" className="map-button" onClick={onRedraw}>{t('place.redraw')}</button>
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
    <p className="map-detail-copy">{t('place.byHand')}</p>
    <button type="button" className="map-button" disabled={busy} onClick={run}>{busy ? t('common.saving') : err ? t('common.tryAgain') : t('place.useGps')}</button>
    {err && <InlineError text={err} />}
  </div>
}
