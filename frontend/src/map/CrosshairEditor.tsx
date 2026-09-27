import type { Map } from 'maplibre-gl'
import { useEffect, useState } from 'react'
import { areaM2, crossesItself, distanceM, formatArea, formatDistance, isNewCorner, nearFirstCorner, type LngLat } from './geometry'
import { setSource } from './layers'
import { t } from '../i18n'

export type Editing = {
  kind: 'stand' | 'camera' | 'zone'
  id?: string
  name: string
  points: LngLat[]
  /** Bedding is drawn first and named after, so the keyboard never covers the map mid-outline. */
  step: 'place' | 'name'
}

/** Where the cross is: the map's centre, followed live while the map moves. */
export function useMapCenter(map: Map | null, active: boolean): LngLat | null {
  const [center, setCenter] = useState<LngLat | null>(null)
  useEffect(() => {
    if (!map || !active) { setCenter(null); return }
    let frame = 0
    const read = () => { const c = map.getCenter(); setCenter([c.lng, c.lat]) }
    const onMove = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; read() }) }
    read()
    map.on('move', onMove)
    return () => { map.off('move', onMove); cancelAnimationFrame(frame) }
  }, [map, active])
  return center
}

/**
 * The fixed cross in the middle of the map. You move the map under it rather than
 * tapping a precise spot with a gloved finger. The tag shows how far the next corner
 * would be from the last one.
 */
export function Crosshair({ editing, center }: { editing: Editing; center: LngLat | null }) {
  const last = editing.points[editing.points.length - 1]
  const tag = editing.kind === 'zone' && editing.step === 'place' && last && center ? formatDistance(distanceM(last, center)) : null
  return <div className="map-cross" aria-hidden="true">
    <svg viewBox="0 0 28 28"><path className="map-cross-halo" d="M14 1v10M14 17v10M1 14h10M17 14h10" /><path d="M14 1v10M14 17v10M1 14h10M17 14h10" /></svg>
    {tag && <span className="map-cross-tag">{tag}</span>}
  </div>
}

/**
 * The bar under the map while something is being placed or drawn.
 *
 * One big "Add corner" button that works with gloves, Undo beside it, and "Finish
 * shape" once there are three corners. On a desktop a click on the map still adds a
 * corner where you click. It sits under the map, above the tab bar, so it never hides
 * the counter or a button under the navigation (B-12).
 *
 * Add corner rests until the cross has moved off the last corner, so a gloved double
 * press can't lay two corners on one spot, and Finish shape waits for an outline
 * that doesn't cross itself (B-10). Cancel stays live while saving: on a connection
 * that never answers it is the way out, and it drops the request.
 */
export default function CrosshairEditor({ map, editing, center, busy, err, onChange, onSave, onCancel, title }: {
  map: Map | null
  editing: Editing
  center: LngLat | null
  busy: boolean
  err: string
  title: string
  onChange: (next: Editing) => void
  onSave: (center: LngLat | null) => void
  onCancel: () => void
}) {
  const [confirmCancel, setConfirmCancel] = useState(false)
  const zone = editing.kind === 'zone'
  const pts = editing.points
  const last = pts[pts.length - 1]

  // The outline so far, the edge the next corner would make (dashed), and the fill.
  useEffect(() => {
    if (!map || !zone) return
    const features: GeoJSON.Feature[] = pts.map(coordinates => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates } }))
    if (pts.length > 1) features.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: editing.step === 'name' ? [...pts, pts[0]] : pts } })
    if (pts.length > 2 && editing.step === 'name') features.push({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[...pts, pts[0]]] } })
    if (editing.step === 'place' && center && last) {
      features.push({ type: 'Feature', properties: { preview: true }, geometry: { type: 'LineString', coordinates: pts.length > 1 ? [last, center, pts[0]] : [last, center] } })
      if (pts.length > 1) features.push({ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[...pts, center, pts[0]]] } })
    }
    setSource(map, 'draft', features)
  }, [map, zone, pts, last, center, editing.step])
  useEffect(() => () => { if (map?.getSource('draft')) setSource(map, 'draft', []) }, [map])

  const cancel = () => {
    if (zone && (pts.length >= 3 || editing.step === 'name') && !confirmCancel) { setConfirmCancel(true); return }
    onCancel()
  }
  const canAdd = !!center && isNewCorner(pts, center)
  const addCorner = () => { if (center && isNewCorner(pts, center)) onChange({ ...editing, points: [...pts, center] }) }
  const area = pts.length >= 3 ? formatArea(areaM2(pts)) : null
  const gap = last && center ? formatDistance(distanceM(last, center)) : null
  const nameMissing = !editing.name.trim()
  // Crossed so far, or would cross once Finish shape closes it back to the first corner.
  const crossed = zone && crossesItself(pts, false)
  const closeCrosses = zone && !crossed && crossesItself(pts)
  const closing = zone && editing.step === 'place' && nearFirstCorner(pts, center)
  const hint = zone && editing.step === 'name' ? t('edit.nameIt')
    : crossed ? t('edit.crosses')
      : closeCrosses ? t('edit.closeCrosses')
        : closing ? t('edit.backAtFirst')
          : zone ? t('edit.moveCorner') : editing.kind === 'stand' ? t('edit.moveStand') : t('edit.moveCamera')

  return <div className="map-editor" role="region" aria-label={title}>
    <div className="map-editor-head">
      <div>
        <strong>{title}</strong>
        <p className={crossed || closeCrosses ? 'map-editor-hint map-editor-hint--warn' : 'map-editor-hint'} aria-live="polite">{hint}</p>
      </div>
      <button type="button" className="map-editor-x" aria-label={t('common.cancel')} onClick={cancel}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>

    {confirmCancel ? <div className="map-editor-confirm" role="alertdialog" aria-label={t('edit.throwAway')}>
      <p>{t('edit.throwAway')}</p>
      <div className="map-editor-row"><button type="button" className="map-button" onClick={onCancel}>{t('notes.throwAwayBtn')}</button><button type="button" className="map-button map-button--primary" onClick={() => setConfirmCancel(false)}>{t('edit.keepDrawing')}</button></div>
    </div> : <>
      {zone && editing.step === 'place' && <>
        <p className="map-editor-status" aria-live="polite">
          <span>{t('edit.corners', { count: pts.length })}</span>
          {gap && <span>{t('edit.fromLast', { gap })}</span>}
          {area && <span>{area}</span>}
        </p>
        <div className="map-editor-row">
          <button type="button" className="map-button map-editor-side" disabled={!pts.length || busy} onClick={() => onChange({ ...editing, points: pts.slice(0, -1) })}>{t('common.undo')}</button>
          <button type="button" className="map-button map-button--primary map-editor-main" disabled={!canAdd || busy} onClick={addCorner}>{t('edit.addCorner')}</button>
          {pts.length >= 3 && <button type="button" className="map-button map-editor-side" disabled={busy || crossed || closeCrosses} onClick={() => onChange({ ...editing, step: 'name' })}>{t('edit.finish')}</button>}
        </div>
      </>}

      {(!zone || editing.step === 'name') && <form className="map-editor-form" onSubmit={e => { e.preventDefault(); if (!nameMissing && !busy) onSave(center) }}>
        {zone && <p className="map-editor-status"><span>{t('edit.corners', { count: pts.length })}</span>{area && <span>{area}</span>}</p>}
        {editing.kind !== 'camera' && (zone || !editing.id) && <label className="map-field">{t('animals.name')}
          <input maxLength={80} value={editing.name} disabled={busy} placeholder={zone ? t('edit.zonePlaceholder') : t('edit.standPlaceholder')} onChange={e => onChange({ ...editing, name: e.target.value })} />
        </label>}
        <div className="map-editor-row">
          {zone && <button type="button" className="map-button map-editor-side" disabled={busy} onClick={() => onChange({ ...editing, step: 'place' })}>{t('common.back')}</button>}
          <button className="map-button map-button--primary map-editor-main" disabled={busy || nameMissing || (!zone && !center)}>{busy ? t('common.saving') : zone ? t('edit.saveBedding') : t('edit.saveHere')}</button>
        </div>
      </form>}
      {err && <p className="map-inline-error" role="alert">{err} <button type="button" className="map-link" disabled={busy} onClick={() => onSave(center)}>{t('common.tryAgain')}</button></p>}
    </>}
  </div>
}
