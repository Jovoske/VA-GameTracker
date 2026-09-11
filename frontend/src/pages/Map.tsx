import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { compass, downwind, windLabel, windColor, type Camera, type MapData } from '../map/geometry'
import { addLayers, fitEstate, renderLayers, setSource, style, type Layers } from '../map/layers'
import '../map/map.css'

type Selection = { kind: 'stand' | 'camera' | 'zone'; id: string }
type Editing = { kind: 'stand' | 'camera' | 'zone'; id?: string; name: string; points: [number, number][] }
const PIN_ICONS = {
  stand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 21V8l7-5 7 5v13M4 11h16M8 21v-6h8v6"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="6" width="18" height="14" rx="3"/><circle cx="12" cy="13" r="4"/><path d="M8 6V3h8v3"/></svg>',
}
export default function MapPage() {
  const [params] = useSearchParams()
  const [selected, setSelected] = useState<Selection | null>(() => params.get('stand') ? { kind: 'stand', id: params.get('stand')! } : null)
  const [data, setData] = useState<MapData | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [admin, setAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [mapErr, setMapErr] = useState('')
  const [ready, setReady] = useState(false)
  const [mapBearing, setMapBearing] = useState(0)
  const [layers, setLayers] = useState<Layers>({ bedding: true, wind: true, exposure: false, routes: false })
  const [layerMenu, setLayerMenu] = useState(false)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const mapEl = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const fitted = useRef(false)
  const markers = useRef<maplibregl.Marker[]>([])
  const editRef = useRef(editing); editRef.current = editing
  const requestId = useRef(0)
  const saving = useRef(false)
  const busyRef = useRef(busy); busyRef.current = busy

  async function load() {
    const request = ++requestId.current
    setLoading(true); setErr('')
    try {
      const [next, cams] = await Promise.all([api<MapData>('/map/tonight'), api<Camera[]>('/cameras')])
      if (request !== requestId.current) return
      setData(next); setCameras(cams)
    } catch (e) { if (request === requestId.current) setErr(`Could not refresh map data. ${(e as Error).message}`) }
    finally { if (request === requestId.current) setLoading(false) }
  }
  useEffect(() => { load(); api<{ role: string }>('/users/me').then(me => setAdmin(me.role === 'admin')).catch(() => {}) }, [])
  useRefetchOnReturn(() => { if (!editRef.current && !busyRef.current) load() }, 120_000)

  useEffect(() => {
    if (!mapEl.current) return
    let instance: maplibregl.Map
    try {
      instance = new maplibregl.Map({ container: mapEl.current, style, center: [-1.3608, 39.0947], zoom: 14, maxPitch: 0, attributionControl: { compact: true } })
    } catch { setMapErr('Your browser could not start the map. Reload this page or try another browser.'); return }
    map.current = instance
    instance.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right')
    instance.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: 'metric' }), 'bottom-left')
    instance.on('rotate', () => setMapBearing(instance.getBearing()))
    instance.on('error', () => setMapErr('Some map imagery could not load. Your saved locations are still listed below.'))
    instance.on('style.load', () => { addLayers(instance); setReady(true) })
    instance.on('click', e => {
      if (busyRef.current) return
      const edit = editRef.current
      if (edit) {
        const point: [number, number] = [e.lngLat.lng, e.lngLat.lat]
        setEditing({ ...edit, points: edit.kind === 'zone' ? [...edit.points, point] : [point] })
      } else if (instance.getLayer('bedding-fill')) {
        const feature = instance.queryRenderedFeatures(e.point, { layers: ['bedding-fill'] })[0]
        if (feature?.properties?.id) { setSelected({ kind: 'zone', id: String(feature.properties.id) }); setConfirmDelete(false) }
      }
    })
    const resize = new ResizeObserver(() => instance.resize())
    resize.observe(mapEl.current)
    return () => { resize.disconnect(); markers.current.forEach(m => m.remove()); markers.current = []; instance.remove(); map.current = null; fitted.current = false }
  }, [])

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    renderLayers(instance, data, layers, selected?.kind === 'stand' ? selected.id : undefined)
    if (!fitted.current) {
      fitEstate(instance, data, cameras)
      const focus = data.stands.find(s => s.id === params.get('stand'))
      if (focus?.lat != null && focus.lon != null) instance.jumpTo({ center: [focus.lon, focus.lat], zoom: 16 })
      fitted.current = true
    }
  }, [ready, data, cameras, layers, selected])

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    markers.current.forEach(m => m.remove()); markers.current = []
    const pin = (kind: 'stand' | 'camera', id: string, name: string, lon: number, lat: number) => {
      const el = document.createElement('button')
      el.dataset.kind = kind; el.dataset.id = id;
      el.type = 'button'; el.className = `map-pin map-pin--${kind}${selected?.id === id && selected.kind === kind ? ' is-selected' : ''}`
      el.setAttribute('aria-label', `${kind === 'stand' ? 'Stand' : 'Camera'}: ${name}`)
      el.title = name
      const icon = document.createElement('span'); icon.className = 'map-pin-icon'; icon.innerHTML = PIN_ICONS[kind]
      const label = document.createElement('span'); label.className = 'map-pin-label'; label.textContent = name
      el.append(icon, label)
      el.addEventListener('click', e => { e.stopPropagation(); if (!editRef.current) { setSelected({ kind, id }); setConfirmDelete(false) } })
      markers.current.push(new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(instance))
    }
    cameras.forEach(c => { if (c.lat != null && c.lng != null) pin('camera', c.id, c.name, c.lng, c.lat) })
    data.stands.forEach(s => { if (s.lat != null && s.lon != null) pin('stand', s.id, s.name, s.lon, s.lat) })
  }, [ready, data, cameras])

  useEffect(() => {
    for (const marker of markers.current) {
      const el = marker.getElement() as HTMLButtonElement
      const active = el.dataset.id === selected?.id && el.dataset.kind === selected?.kind
      el.classList.toggle('is-selected', active)
      el.setAttribute('aria-pressed', String(active))
      el.disabled = !!editing
      el.style.pointerEvents = editing ? 'none' : ''
    }
  }, [ready, data, cameras, selected, editing])

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready) return
    instance.getCanvas().style.cursor = editing ? 'crosshair' : ''
    const points = editing?.points ?? []
    const features: GeoJSON.Feature[] = points.map(coordinates => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates } }))
    if (points.length > 1) features.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: points.length > 2 ? [...points, points[0]] : points } })
    setSource(instance, 'draft', features)
  }, [ready, editing])

  async function saveEdit() {
    if (!editing || saving.current || !editing.name.trim() || editing.points.length < (editing.kind === 'zone' ? 3 : 1)) return
    saving.current = true; setBusy(true); setErr(''); setNotice('')
    try {
      const [lon, lat] = editing.points[0]
      if (editing.kind === 'zone') await api('/zones', { method: 'POST', body: JSON.stringify({ name: editing.name.trim(), kind: 'bedding', polygon: { type: 'Polygon', coordinates: [[...editing.points, editing.points[0]]] } }) })
      else if (editing.kind === 'camera') await api(`/cameras/${editing.id}/location`, { method: 'PUT', body: JSON.stringify({ lat, lng: lon }) })
      else await api(editing.id ? `/stands/${editing.id}` : '/stands', { method: editing.id ? 'PATCH' : 'POST', body: JSON.stringify({ name: editing.name.trim(), lat, lon }) })
      setEditing(null); setNotice('Location saved.'); await load()
    } catch (e) { setErr(`Could not save. ${(e as Error).message}`) }
    finally { saving.current = false; setBusy(false) }
  }
  async function removeSelected() {
    if (!selected || selected.kind === 'camera' || saving.current) return
    saving.current = true; setBusy(true); setErr('')
    try {
      await api(`/${selected.kind === 'stand' ? 'stands' : 'zones'}/${selected.id}`, { method: 'DELETE' })
      setSelected(null); setConfirmDelete(false); setNotice('Location removed.'); await load()
    } catch (e) { setErr(`Could not remove this location. ${(e as Error).message}`) }
    finally { saving.current = false; setBusy(false) }
  }
  function choose(selection: Selection, lon?: number | null, lat?: number | null) {
    setSelected(selection); setConfirmDelete(false)
    if (lon != null && lat != null) map.current?.jumpTo({ center: [lon, lat], zoom: Math.max(15, map.current.getZoom()) })
  }
  const stand = selected?.kind === 'stand' ? data?.stands.find(s => s.id === selected.id) : null
  const camera = selected?.kind === 'camera' ? cameras.find(c => c.id === selected.id) : null
  const zone = selected?.kind === 'zone' ? data?.zones.find(z => z.id === selected.id) : null
  const air = data?.airflow
  const from = air?.source !== 'unknown' ? air?.wind_dir_deg : null
  const speed = air?.wind_speed_kmh
  const name = stand?.name ?? camera?.name ?? zone?.name
  const unplaced = cameras.filter(c => c.lat == null || c.lng == null)

  return <div className="estate-map">
    <div className="map-page-heading"><div><h1>Estate map</h1><p>Read the ground. Plan your position.</p></div><Link className="map-button" to="/stands">Tonight’s stands ↗</Link></div>
    {err && <div className="map-message map-message--error" role="alert">{err}<button onClick={load} disabled={loading || busy}>Retry loading data</button></div>}
    {notice && <div className="map-message" role="status">{notice}<button onClick={() => setNotice('')}>Dismiss</button></div>}
    <section className="map-workspace" aria-label="Estate map and controls">
      <div className="map-windbar">
        <div className="wind-direction" aria-hidden="true"><svg viewBox="0 0 40 40" style={{ transform: from == null ? undefined : `rotate(${downwind(from) - mapBearing}deg)` }}><circle cx="20" cy="20" r="18"/>{from != null && <path d="M20 29V11m-6 6 6-6 6 6"/>}</svg></div>
        <div className="map-wind-reading"><span>{air?.source === 'katabatic' || air?.source === 'anabatic' ? 'Estimated terrain airflow' : 'Forecast wind'}</span><strong>{from != null ? `From ${compass(from)} → ${compass(downwind(from))}` : loading ? 'Loading conditions…' : 'Direction uncertain'}</strong></div>
        <div className="map-wind-speed"><strong>{speed == null ? '—' : Math.round(speed * 10) / 10}</strong><span>km/h</span></div>
      </div>
      {editing && <div className="map-edit-toolbar"><form onSubmit={e => { e.preventDefault(); saveEdit() }}>
          <div className="map-section-heading"><h2>{editing.kind === 'zone' ? 'Draw bedding area' : editing.id ? 'Edit location' : 'New stand'}</h2><button className="map-link" disabled={busy} type="button" onClick={() => setEditing(null)}>Cancel</button></div>
          <label className="map-field">Name<input autoFocus maxLength={80} value={editing.name} disabled={editing.kind === 'camera' || busy} onChange={e => setEditing({ ...editing, name: e.target.value })}/></label>
          <p className="map-detail-copy">{editing.kind === 'zone' ? 'Add at least three points around the area where animals rest. The dashed outline is a draft until you save.' : 'Choose the actual location on the map above. The highlighted point is a draft until you save.'}</p>
          <div className="map-actions">{editing.kind === 'zone' && <button type="button" className="map-button" disabled={!editing.points.length || busy} onClick={() => setEditing({ ...editing, points: editing.points.slice(0, -1) })}>Undo point</button>}<button className="map-button map-button--primary" disabled={busy || !editing.name.trim() || editing.points.length < (editing.kind === 'zone' ? 3 : 1)}>{busy ? 'Saving…' : 'Save location'}</button></div>
        </form></div>}
      <div className="map-stage">
        <div ref={mapEl} className="map-canvas" aria-label="Interactive estate map" />
        <div className="map-tools"><button className="map-button" aria-expanded={layerMenu} onClick={() => setLayerMenu(!layerMenu)}>Layers</button><button className="map-button" onClick={() => { if (map.current && data) fitEstate(map.current, data, cameras) }} disabled={!data || !ready}>Fit estate</button></div>
        {layerMenu && <div className="map-layer-menu"><strong>Show on map</strong>{([['wind', 'Wind & scent direction'], ['bedding', 'Bedding areas'], ['exposure', 'Estimated scent exposure'], ['routes', 'Inferred animal routes']] as const).map(([key, label]) => <label key={key}><input type="checkbox" checked={layers[key]} onChange={e => setLayers(v => ({ ...v, [key]: e.target.checked }))}/>{label}</label>)}<p>Exposure estimates concern scent reaching mapped bedding, not shooting safety. Routes are inferred from sightings.</p></div>}
        {!ready && !mapErr && <div className="map-loading" role="status">Loading satellite map…</div>}
        {mapErr && <div className="map-tile-error" role="status">{mapErr}<button onClick={() => { setMapErr(''); map.current?.setStyle(style); setReady(false) }}>Retry imagery</button></div>}
        {!editing && name && <div className="map-selection-peek"><div><small>{stand ? 'Stand' : camera ? 'Camera' : 'Bedding area'}</small><strong>{name}</strong></div><button className="map-link" onClick={() => document.getElementById('location-details')?.scrollIntoView({ block: 'center' })}>Details ↓</button><button className="map-link" aria-label="Clear selected location" onClick={() => setSelected(null)}>×</button></div>}
        {editing && <div className="map-edit-hint">{editing.kind === 'zone' ? `Tap around the bedding area · ${editing.points.length} points` : 'Tap the map to choose a position. Save when ready.'}</div>}
      </div>
      <div className="map-key"><span><i className="key-camera"/>Camera</span><span><i className="key-stand"/>Stand</span><span><i className="key-wind"/>Downwind scent direction</span><span className="map-key-note">Select a stand to see its estimated scent area.</span></div>
    </section>
    <div className="map-lower">
      <section id="location-details" className="map-detail" aria-label="Selected location">
        {editing ? <p className="map-detail-copy">Use the editing controls above the map to save or cancel this draft.</p> : name ? <>
          <div className="map-section-heading"><div><span className="map-eyebrow">{stand ? 'Stand' : camera ? 'Camera' : 'Bedding area'}</span><h2>{name}</h2></div><button className="map-link" onClick={() => { setSelected(null); setConfirmDelete(false) }}>Clear</button></div>
          {stand && <><p className="stand-wind-label" style={{ color: windColor(stand.wind.status) }}>{windLabel(stand.wind.status)}</p><p className="map-detail-copy">{stand.wind.text}</p>{stand.wind.source && stand.wind.source !== 'synoptic' && <p className="map-detail-copy">Local terrain can change airflow here, so this direction may differ from the estate forecast above.</p>}<Link className="map-button map-button--primary" to={`/stands?stand=${stand.id}`}>Open stand & reservation →</Link></>}
          {camera && <><p className="map-detail-copy">{camera.sightings} photos not marked empty · Battery {camera.battery_pct == null ? 'unknown' : `${camera.battery_pct}%`}</p><Link className="map-button" to="/cameras">View camera photos →</Link></>}
          {zone && <p className="map-detail-copy">Mapped resting area used to estimate whether downwind scent may reach animals.</p>}
          {admin && <div className="map-actions">{!zone && <button className="map-button" onClick={() => setEditing({ kind: stand ? 'stand' : 'camera', id: selected!.id, name: name!, points: stand?.lat != null && stand.lon != null ? [[stand.lon, stand.lat]] : camera?.lat != null && camera.lng != null ? [[camera.lng, camera.lat]] : [] })}>Edit location</button>}{!camera && <button className="map-link" disabled={busy} onClick={() => setConfirmDelete(true)}>Remove…</button>}</div>}
          {confirmDelete && <div className="map-message">Remove “{name}”? This removes its map location.<div className="map-actions"><button disabled={busy} onClick={removeSelected}>Confirm removal</button><button disabled={busy} onClick={() => setConfirmDelete(false)}>Keep location</button></div></div>}
        </> : <><span className="map-eyebrow">Explore the estate</span><h2>A clear view of your ground</h2><p className="map-detail-copy">Select a camera, stand, or bedding area for details. Arrows show where scent travels. Their direction stays fixed to the ground as you rotate the map.</p>{air?.text && <p className="map-detail-copy">{air.text}</p>}</>}
      </section>
      <section className="map-location-list" aria-label="Map locations"><div className="map-section-heading"><h2>Locations</h2><span>{(data?.stands.length ?? 0) + cameras.length}</span></div>
        {loading && !data && <p role="status">Loading locations…</p>}
        {data?.stands.map(s => <button className={`map-location-row${selected?.id === s.id ? ' is-selected' : ''}`} key={s.id} onClick={() => choose({ kind: 'stand', id: s.id }, s.lon, s.lat)} disabled={!!editing}><span className="location-type">Stand</span><strong>{s.name}</strong><span>{s.lat == null || s.lon == null ? 'Needs position' : '↗'}</span></button>)}
        {cameras.map(c => <button className={`map-location-row${selected?.id === c.id ? ' is-selected' : ''}`} key={c.id} onClick={() => choose({ kind: 'camera', id: c.id }, c.lng, c.lat)} disabled={!!editing}><span className="location-type">Camera</span><strong>{c.name}</strong><span>{c.lat == null || c.lng == null ? 'Needs position' : '↗'}</span></button>)}
        {data && !data.stands.length && !cameras.length && <p className="map-detail-copy">No locations yet. Connect cameras in Settings or add a stand.</p>}
        {!!unplaced.length && <p className="map-detail-copy">{unplaced.length} camera{unplaced.length === 1 ? '' : 's'} need a position. Select one to place it.</p>}
        {admin && !editing && <div className="map-actions"><button className="map-button" onClick={() => setEditing({ kind: 'stand', name: '', points: [] })}>Add stand</button><button className="map-button" onClick={() => setEditing({ kind: 'zone', name: '', points: [] })}>Draw bedding area</button></div>}
        {data && !data.terrain_loaded && <div className="map-terrain"><p className="map-detail-copy">Terrain data is needed to estimate airflow on calm nights.</p><button className="map-link" disabled={busy} onClick={async () => { setBusy(true); setErr(''); try { await api('/terrain/refresh', { method: 'POST' }); setNotice('Terrain data loaded.'); await load() } catch (e) { setErr(`Could not load terrain. ${(e as Error).message}`) } finally { setBusy(false) } }}>{busy ? 'Working…' : 'Load terrain data'}</button></div>}
      </section>
    </div>
  </div>
}
