import { FrameCornersIcon } from '@phosphor-icons/react/dist/csr/FrameCorners'
import { NavigationArrowIcon } from '@phosphor-icons/react/dist/csr/NavigationArrow'
import { RulerIcon } from '@phosphor-icons/react/dist/csr/Ruler'
import { StackIcon } from '@phosphor-icons/react/dist/csr/Stack'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { type CSSProperties, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { BASE_SOURCES, CATASTRO, baseLabel, baseSource, mapStyle, readPrefs, retryBase, showBase, showCatastro, writePrefs, type BaseId, type MapPrefs } from '../map/basemaps'
import BottomSheet, { type Snap } from '../map/BottomSheet'
import { CameraBody, CameraHeader } from '../map/CameraSheet'
import CrosshairEditor, { Crosshair, useMapCenter, type Editing } from '../map/CrosshairEditor'
import { setUnsavedDraft } from '../map/draftGuard'
import { direction, downwind, validLngLat, type Camera, type LngLat, type MapData } from '../map/geometry'
import { addLayers, fitEstate, renderLayers } from '../map/layers'
import MapFab from '../map/MapFab'
import MapSheet, { type Unplaced } from '../map/MapSheet'
import { StandBody, StandHeader, ZoneBody, ZoneHeader } from '../map/PlaceSheet'
import ScalePill from '../map/ScalePill'
import { useMeasure } from '../map/useMeasure'
import { useMyPosition } from '../map/useMyPosition'
import '../map/map.css'

type Selection = { kind: 'stand' | 'camera' | 'zone'; id: string }
const PIN_ICONS = {
  stand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 21V8l7-5 7 5v13M4 11h16M8 21v-6h8v6"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="6" width="18" height="14" rx="3"/><circle cx="12" cy="13" r="4"/><path d="M8 6V3h8v3"/></svg>',
}
// Names under the pins from this zoom in; further out they would pile on top of each other.
const LABEL_ZOOM = 15
// A base map that fails this many tiles in a row, with none getting through, is down
// (or blocked on this network), not just slow. One timeout on weak signal is not this.
const FALLBACK_AFTER = 4
const ESTATE_CENTER: LngLat = [-1.3608, 39.0947]

const initialSelection = (params: URLSearchParams): Selection | null =>
  params.get('stand') ? { kind: 'stand', id: params.get('stand')! } : params.get('camera') ? { kind: 'camera', id: params.get('camera')! } : null

export default function MapPage() {
  const [params] = useSearchParams()
  const [selected, setSelected] = useState<Selection | null>(() => initialSelection(params))
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [snap, setSnap] = useState<Snap>('half')
  const [data, setData] = useState<MapData | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [admin, setAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [notice, setNotice] = useState('')
  const [fatal, setFatal] = useState('')
  const [ready, setReady] = useState(false)
  const [mapObj, setMapObj] = useState<maplibregl.Map | null>(null)
  const [bearing, setBearing] = useState(0)
  const [zoom, setZoom] = useState(14)
  const [prefs, setPrefsState] = useState<MapPrefs>(readPrefs)
  const [activeBase, setActiveBase] = useState<BaseId>(prefs.base)
  const [fallbackFrom, setFallbackFrom] = useState<BaseId | null>(null)
  const [tileErr, setTileErr] = useState(false)
  const [catastroErr, setCatastroErr] = useState(false)
  const [windOpen, setWindOpen] = useState(false)
  const [editing, setEditing] = useState<Editing | null>(null)
  const [editBusy, setEditBusy] = useState(false)
  const [editErr, setEditErr] = useState('')
  const [terrainBusy, setTerrainBusy] = useState(false)
  const [terrainErr, setTerrainErr] = useState('')
  const mapEl = useRef<HTMLDivElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const fitted = useRef(false)
  const markers = useRef<maplibregl.Marker[]>([])
  const editRef = useRef(editing); editRef.current = editing
  const busyRef = useRef(editBusy); busyRef.current = editBusy
  const activeBaseRef = useRef(activeBase); activeBaseRef.current = activeBase
  const requestId = useRef(0)
  const saving = useRef(false)
  const lastCorner = useRef({ t: 0, x: 0, y: 0 })
  // Tile health, per source. Kept in a ref: tiles report far too often for state.
  const tiles = useRef({ fails: {} as Record<string, number>, errSinceIdle: 0, okSinceErr: 0 })

  const measure = useMeasure(mapObj, ready)
  const measureRef = useRef(measure); measureRef.current = measure
  const me = useMyPosition(mapObj, ready)
  const center = useMapCenter(mapObj, !!editing)

  const load = useCallback(async () => {
    const request = ++requestId.current
    setLoading(true); setErr('')
    try {
      const [next, cams] = await Promise.all([api<MapData>('/map/tonight'), api<Camera[]>('/cameras')])
      if (request !== requestId.current) return
      setData(next); setCameras(cams)
    } catch (e) { if (request === requestId.current) setErr(`Couldn’t load the map. ${(e as Error).message}`) }
    finally { if (request === requestId.current) setLoading(false) }
  }, [])
  useEffect(() => { load(); api<{ role: string }>('/auth/me').then(u => setAdmin(u.role === 'admin')).catch(() => {}) }, [load])
  useRefetchOnReturn(() => { if (!editRef.current && !busyRef.current) load() }, 120_000)

  function setPrefs(next: MapPrefs) { setPrefsState(next); writePrefs(next) }

  // ── the map itself ──
  useEffect(() => {
    if (!mapEl.current) return
    let instance: maplibregl.Map
    try {
      instance = new maplibregl.Map({ container: mapEl.current, style: mapStyle(prefs), center: ESTATE_CENTER, zoom: 14, maxZoom: 20, maxPitch: 0, attributionControl: false })
    } catch { setFatal('The map couldn’t start on this phone. Reload the page, or use Stands and Cameras meanwhile.'); return }
    map.current = instance
    // Browser checks read the live map in development builds only.
    if (import.meta.env.DEV) (window as unknown as { __gsMap?: maplibregl.Map }).__gsMap = instance
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    instance.on('rotate', () => setBearing(instance.getBearing()))
    // A pinch that twists a few degrees shouldn't leave the estate skewed (B-23).
    instance.on('rotateend', () => { const b = instance.getBearing(); if (b !== 0 && Math.abs(b) < 12) instance.easeTo({ bearing: 0, duration: 200 }) })
    instance.on('zoomend', () => setZoom(Math.round(instance.getZoom() * 10) / 10))
    instance.on('style.load', () => { addLayers(instance); setReady(true); setMapObj(instance) })

    // Only the base picture raises the banner, and only its own tiles. A failed
    // property-lines tile is reported next to its switch instead (B-01).
    instance.on('error', (e: maplibregl.ErrorEvent & { sourceId?: string }) => {
      const source = e.sourceId, t = tiles.current
      if (!source) return
      t.fails[source] = (t.fails[source] ?? 0) + 1
      if (source === CATASTRO) { if (t.fails[source] >= 2) setCatastroErr(true); return }
      if (!BASE_SOURCES.includes(source) || source !== baseSource(activeBaseRef.current)) return
      t.errSinceIdle++; t.okSinceErr = 0
      if (activeBaseRef.current !== 'world' && t.fails[source] >= FALLBACK_AFTER) {
        // The Spanish servers aren't answering here. Show the world imagery and say so.
        setFallbackFrom(activeBaseRef.current); setActiveBase('world'); setTileErr(false)
        t.fails = {}; t.errSinceIdle = 0
      } else setTileErr(true)
    })
    instance.on('sourcedata', (e: maplibregl.MapSourceDataEvent) => {
      if (!e.tile || !e.sourceId) return
      const t = tiles.current
      t.fails[e.sourceId] = 0
      if (e.sourceId === CATASTRO) setCatastroErr(false)
      if (e.sourceId === baseSource(activeBaseRef.current)) t.okSinceErr++
    })
    // The banner goes by itself once the picture has loaded again with nothing failing.
    instance.on('idle', () => {
      const t = tiles.current
      if (t.okSinceErr > 0 && t.errSinceIdle === 0) setTileErr(false)
      t.errSinceIdle = 0
    })

    instance.on('click', e => {
      if (busyRef.current) return
      const edit = editRef.current
      const pointer = (e.originalEvent as PointerEvent).pointerType
      const touch = pointer === 'touch' || (!pointer && window.matchMedia?.('(pointer: coarse)').matches)
      if (edit) {
        // On a phone the cross places things. With a mouse a click still does, where you click.
        if (touch) return
        if (edit.kind !== 'zone') { instance.easeTo({ center: e.lngLat, duration: 200 }); return }
        if (edit.step !== 'place') return
        const last = lastCorner.current, now = Date.now()
        // The second click of a double click is not a second corner (B-13).
        if (now - last.t < 350 && Math.hypot(e.point.x - last.x, e.point.y - last.y) < 20) return
        lastCorner.current = { t: now, x: e.point.x, y: e.point.y }
        setEditing({ ...edit, points: [...edit.points, [e.lngLat.lng, e.lngLat.lat]] })
        return
      }
      if (measureRef.current.on) { measureRef.current.add([e.lngLat.lng, e.lngLat.lat]); return }
      const feature = instance.getLayer('bedding-fill') ? instance.queryRenderedFeatures(e.point, { layers: ['bedding-fill'] })[0] : undefined
      if (feature?.properties?.id) { setSelected({ kind: 'zone', id: String(feature.properties.id) }); setSettingsOpen(false); setSnap('half') }
      else { setSelected(null); setSettingsOpen(false) }
    })
    const resize = new ResizeObserver(() => instance.resize())
    resize.observe(mapEl.current)
    return () => { resize.disconnect(); markers.current.forEach(m => m.remove()); markers.current = []; instance.remove(); map.current = null; setMapObj(null); fitted.current = false }
    // The map is built once; later preference changes flip layers on the live style.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Base picture and property lines follow the choice without rebuilding the style.
  useEffect(() => { setActiveBase(prefs.base); setFallbackFrom(null); setTileErr(false); tiles.current = { fails: {}, errSinceIdle: 0, okSinceErr: 0 } }, [prefs.base])
  useEffect(() => { if (ready && map.current) showBase(map.current, activeBase) }, [ready, activeBase])
  useEffect(() => { if (ready && map.current) showCatastro(map.current, prefs.catastro); if (!prefs.catastro) setCatastroErr(false) }, [ready, prefs.catastro])

  /** Try again: ask for the picture's tiles again and nothing else. The style, the drawn layers and `ready` are left alone (B-01, I-11). */
  function retryTiles() {
    const instance = map.current
    if (!instance) return
    tiles.current = { fails: {}, errSinceIdle: 0, okSinceErr: 0 }
    setTileErr(false)
    // Back from the fallback: the Spanish layer was hidden, so its failed tiles are
    // already gone and showing it again asks for them afresh.
    if (fallbackFrom) { setFallbackFrom(null); setActiveBase(fallbackFrom); showBase(instance, fallbackFrom); return }
    retryBase(instance, activeBase, () => activeBaseRef.current === activeBase)
  }

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    renderLayers(instance, data, prefs.layers, selected?.kind === 'stand' ? selected.id : undefined)
    if (!fitted.current) {
      fitEstate(instance, data, cameras)
      fitted.current = true
      const focus = selected?.kind === 'stand' ? data.stands.find(s => s.id === selected.id) : selected?.kind === 'camera' ? cameras.find(c => c.id === selected.id) : null
      const lon = focus && ('lon' in focus ? focus.lon : focus.lng), lat = focus?.lat
      if (validLngLat(lon, lat)) reveal(lon as number, lat as number, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, data, cameras, prefs.layers, selected])

  /** Bring a place into the part of the map the sheet doesn't cover. */
  function reveal(lon: number, lat: number, always = false) {
    const instance = map.current, stage = stageRef.current
    if (!instance || !stage) return
    const w = stage.clientWidth, h = stage.clientHeight, wide = w >= 641
    const p = instance.project([lon, lat])
    // Room for the pin and its name above the sheet's middle height, and off the edges.
    const covered = wide ? p.x < 480 && p.y > h * .5 - 90 : p.y > h * .5 - 90
    if (!always && !covered && p.x > 40 && p.x < w - 40 && p.y > 40) return
    instance.easeTo({ center: [lon, lat], zoom: always ? Math.max(16, instance.getZoom()) : instance.getZoom(), offset: wide ? [Math.min(230, w / 4), -h * .1] : [0, -h * .25], duration: always ? 0 : 300 })
  }
  const select = useCallback((kind: 'stand' | 'camera', id: string, lon: number, lat: number) => {
    setSelected({ kind, id }); setSettingsOpen(false); setSnap('half')
    reveal(lon, lat)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const selectRef = useRef(select); selectRef.current = select

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    markers.current.forEach(m => m.remove()); markers.current = []
    const pin = (kind: 'stand' | 'camera', id: string, name: string, lon: number, lat: number) => {
      const el = document.createElement('button')
      el.dataset.kind = kind; el.dataset.id = id
      el.type = 'button'; el.className = `map-pin map-pin--${kind}`
      el.setAttribute('aria-label', `${kind === 'stand' ? 'Stand' : 'Camera'}: ${name}`)
      const icon = document.createElement('span'); icon.className = 'map-pin-icon'; icon.innerHTML = PIN_ICONS[kind]
      const label = document.createElement('span'); label.className = 'map-pin-label'; label.textContent = name
      el.append(icon, label)
      el.addEventListener('click', e => { e.stopPropagation(); if (!editRef.current && !measureRef.current.on) selectRef.current(kind, id, lon, lat) })
      markers.current.push(new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(instance))
    }
    cameras.forEach(c => { if (validLngLat(c.lng, c.lat)) pin('camera', c.id, c.name, c.lng!, c.lat!) })
    data.stands.forEach(s => { if (validLngLat(s.lon, s.lat)) pin('stand', s.id, s.name, s.lon!, s.lat!) })
  }, [ready, data, cameras])

  useEffect(() => {
    const inert = !!editing || measure.on
    for (const marker of markers.current) {
      const el = marker.getElement() as HTMLButtonElement
      const active = el.dataset.id === selected?.id && el.dataset.kind === selected?.kind
      el.classList.toggle('is-selected', active)
      el.setAttribute('aria-pressed', String(active))
      el.disabled = inert
      el.style.pointerEvents = inert ? 'none' : ''
    }
  }, [ready, data, cameras, selected, editing, measure.on])

  // While drawing, a double tap must not zoom and add a corner at once (B-13).
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (editing) instance.doubleClickZoom.disable(); else instance.doubleClickZoom.enable()
  }, [editing != null])
  useEffect(() => {
    const what = editing?.kind === 'zone' && editing.points.length ? 'this bedding outline' : editing && !editing.id && editing.name.trim() ? 'this stand' : ''
    setUnsavedDraft(what)
    if (!what) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [editing])
  useEffect(() => () => setUnsavedDraft(''), [])
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(t) }, [notice])

  // ── placing and drawing ──
  function startEdit(next: Omit<Editing, 'step' | 'points'> & { at?: [number | null | undefined, number | null | undefined] }) {
    const instance = map.current
    const [lon, lat] = next.at ?? []
    if (instance && validLngLat(lon, lat)) instance.jumpTo({ center: [lon as number, lat as number], zoom: Math.max(16, instance.getZoom()) })
    measure.stop(); setSettingsOpen(false); setEditErr('')
    setEditing({ kind: next.kind, id: next.id, name: next.name, points: [], step: 'place' })
  }
  async function saveEdit(at: LngLat | null) {
    const e = editRef.current
    if (!e || saving.current || !e.name.trim()) return
    // The live centre, not the last rendered one: the cross is wherever the map is now.
    const live = map.current?.getCenter()
    const point: LngLat | null = live ? [live.lng, live.lat] : at
    if (e.kind === 'zone' ? e.points.length < 3 : !point) return
    saving.current = true; setEditBusy(true); setEditErr('')
    try {
      let created: { id: string } | undefined
      if (e.kind === 'zone') await api('/zones', { method: 'POST', body: JSON.stringify({ name: e.name.trim(), kind: 'bedding', polygon: { type: 'Polygon', coordinates: [[...e.points, e.points[0]]] } }) })
      else if (e.kind === 'camera') await api(`/cameras/${e.id}/location`, { method: 'PUT', body: JSON.stringify({ lat: point![1], lng: point![0] }) })
      else if (e.id) await api(`/stands/${e.id}`, { method: 'PATCH', body: JSON.stringify({ lat: point![1], lon: point![0] }) })
      else created = await api<{ id: string }>('/stands', { method: 'POST', body: JSON.stringify({ name: e.name.trim(), lat: point![1], lon: point![0] }) })
      // The draft stays until the new positions are in, so the pin never jumps back (B-17).
      await load()
      setEditing(null)
      if (created?.id) { setSelected({ kind: 'stand', id: created.id }); setSnap('peek') }
      else if (e.id) setSnap('peek')
      setNotice(e.kind === 'zone' ? 'Bedding saved.' : 'Saved.')
    } catch (x) { setEditErr(`That didn’t save. ${(x as Error).message}`) }
    finally { saving.current = false; setEditBusy(false) }
  }
  async function remove(kind: 'stand' | 'zone', id: string) {
    try {
      await api(`/${kind === 'stand' ? 'stands' : 'zones'}/${id}`, { method: 'DELETE' })
    } catch (x) {
      const status = (x as Error & { status?: number }).status
      if (kind === 'stand' && status === 409) throw Object.assign(new Error('This stand has sit history, so it can’t be removed. Rename it instead.'), { final: true })
      throw new Error(`That didn’t remove. ${(x as Error).message}`)
    }
    // Said once the map shows it, so the pin never lingers under 'Removed'.
    await load(); setSelected(null); setNotice('Removed from the map.')
  }
  async function rename(id: string, name: string) {
    try { await api(`/stands/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }) }
    catch (x) { throw new Error(`That didn’t save. ${(x as Error).message}`) }
    await load(); setNotice('Renamed.')
  }
  async function loadTerrain() {
    setTerrainBusy(true); setTerrainErr('')
    try { await api('/terrain/refresh', { method: 'POST' }); await load(); setNotice('Hill shape loaded.') }
    catch (x) { console.warn('terrain', x); setTerrainErr('Couldn’t load the hill shape. Check the signal and try again later.') }
    finally { setTerrainBusy(false) }
  }

  const stand = selected?.kind === 'stand' ? data?.stands.find(s => s.id === selected.id) : null
  const camera = selected?.kind === 'camera' ? cameras.find(c => c.id === selected.id) : null
  const zone = selected?.kind === 'zone' ? data?.zones.find(z => z.id === selected.id) : null
  const air = data?.airflow
  const from = air?.source !== 'unknown' ? air?.wind_dir_deg : null
  const speed = air?.wind_speed_kmh
  const unplaced: Unplaced[] = [
    ...(data?.stands ?? []).filter(s => !validLngLat(s.lon, s.lat)).map(s => ({ kind: 'stand' as const, id: s.id, name: s.name })),
    ...cameras.filter(c => !validLngLat(c.lng, c.lat)).map(c => ({ kind: 'camera' as const, id: c.id, name: c.name })),
  ]
  const sheet = editing ? null : (stand || camera || zone) ? 'place' : settingsOpen ? 'settings' : null
  const closeSheet = () => { setSelected(null); setSettingsOpen(false) }
  const onSheetHeight = useCallback((px: number) => {
    const stage = stageRef.current
    if (!stage) return
    stage.style.setProperty('--sheet-h', `${px}px`)
    stage.dataset.sheet = px > stage.clientHeight * .7 ? 'tall' : px > 0 ? 'open' : ''
  }, [])
  const baseNote = fallbackFrom ? `${baseLabel(fallbackFrom)} from IGN isn’t loading here, so this is ${baseLabel('world')} for now.` : null
  const tileNotice = fallbackFrom && !tileErr ? `${baseLabel(fallbackFrom)} isn’t loading, so this is ${baseLabel('world')}.` : tileErr ? 'Part of the map picture didn’t load. Your stands and cameras are still on it.' : ''
  const editTitle = editing ? editing.kind === 'zone' ? 'Draw bedding' : editing.id ? `Move ${editing.name}` : 'New stand' : ''

  if (fatal) return <div className="map-page map-page--fatal">
    <h1 className="page-title">Map</h1>
    <div className="map-message map-message--error" role="alert">{fatal}</div>
    <div className="map-actions"><Link className="map-button" to="/stands">Stands</Link><Link className="map-button" to="/cameras">Cameras</Link></div>
  </div>

  return <div className="map-page" style={{ '--pin-scale': prefs.bigPins ? 1.25 : 1 } as CSSProperties}>
    <h1 className="sr-only">Map</h1>
    <button type="button" className="map-windbar" aria-expanded={windOpen} aria-controls="map-wind-more" onClick={() => setWindOpen(v => !v)}>
      <span className="wind-direction" aria-hidden="true"><svg viewBox="0 0 40 40" style={{ transform: from == null ? undefined : `rotate(${downwind(from) - bearing}deg)` }}><circle cx="20" cy="20" r="18" />{from != null && <path d="M20 29V11m-6 6 6-6 6 6" />}</svg></span>
      <span className="map-wind-reading">
        <span>{air?.source === 'katabatic' ? 'Calm evening. Cold air sliding downhill' : air?.source === 'anabatic' ? 'Calm and sunny. Air drifting uphill' : 'Wind tonight'}</span>
        <strong>{from != null ? `From the ${direction(from)}` : loading && !data ? 'Checking…' : 'Too light to call'}</strong>
        {from != null && <em>Scent goes {direction(downwind(from))}</em>}
      </span>
      <span className="map-wind-speed"><strong>{speed == null ? '—' : Math.round(speed)}</strong><span>km/h</span></span>
      <span className="map-wind-chevron" aria-hidden="true">{windOpen ? '▴' : '▾'}</span>
    </button>
    <div className="map-stage" ref={stageRef} data-editing={editing ? 'true' : undefined} data-labels={zoom >= LABEL_ZOOM ? 'on' : undefined}>
      <div className="map-canvas-wrap">
        <div ref={mapEl} className="map-canvas" aria-label="Estate map. Drag to move, pinch to zoom." />
        {windOpen && <div id="map-wind-more" className="map-wind-more">
          {air?.text && <p>{air.text}</p>}
          <p>Arrows show where scent goes from each stand. Tap a stand to see how far it carries.</p>
          <p className="map-caveat">An indication only. Wind near the ground swirls.</p>
        </div>}
        <ScalePill map={mapObj} />
        <div className="map-notices">
          {err && <div className="map-pill map-pill--error" role="alert"><span>{err}</span><button type="button" onClick={load} disabled={loading}>Try again</button></div>}
          {tileNotice && <div className="map-pill" role="status"><span>{tileNotice}</span><button type="button" onClick={retryTiles}>Try again</button></div>}
          {measure.on && <div className="map-pill map-pill--measure" role="status">
            <span>{measure.result ?? (measure.points.length ? 'Now tap the second point.' : 'Tap two points to measure.')}</span>
            {measure.result && <button type="button" onClick={measure.clear}>Clear</button>}
            <button type="button" onClick={measure.stop}>Done</button>
          </div>}
          {notice && <div className="map-pill" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice('')}>OK</button></div>}
        </div>
        {!ready && <div className="map-loading" role="status">Loading map…</div>}

        {!editing && <div className="map-fabs map-fabs--right">
          <MapFab label="Map type, layers and tools" pressed={settingsOpen} onClick={() => { setSelected(null); setSettingsOpen(v => !v); setSnap('half') }}><StackIcon size={22} /></MapFab>
          <MapFab label="Point the map north" onClick={() => map.current?.easeTo({ bearing: 0, pitch: 0, duration: 300 })}>
            <svg className="map-north" viewBox="0 0 24 24" aria-hidden="true" style={{ transform: `rotate(${-bearing}deg)` }}>
              <path className="map-north-n" d="M12 3.5 15 12H9z" /><path className="map-north-s" d="M12 20.5 9 12h6z" /><path className="map-north-tick" d="M12 1v3" />
            </svg>
          </MapFab>
          <MapFab label="Fit the estate" disabled={!data || !ready} onClick={() => { if (map.current && data) fitEstate(map.current, data, cameras, 300) }}><FrameCornersIcon size={22} /></MapFab>
        </div>}
        {!editing && <div className="map-fabs map-fabs--left">
          {me.message && <div className="map-pill map-pill--side" role="status"><span>{me.message}</span><button type="button" aria-label="Dismiss" onClick={me.clearMessage}>OK</button></div>}
          <MapFab label={measure.on ? 'Stop measuring' : 'Measure a distance'} pressed={measure.on} onClick={() => { measure.toggle(); closeSheet() }}><RulerIcon size={22} /></MapFab>
          <MapFab label={me.on ? 'Hide where I am' : 'Show where I am'} pressed={me.on} onClick={me.toggle}><NavigationArrowIcon size={22} /></MapFab>
        </div>}
        {editing && <Crosshair editing={editing} center={center} />}

        {sheet && <BottomSheet
          label={sheet === 'settings' ? 'Map settings' : stand ? `Stand: ${stand.name}` : camera ? `Camera: ${camera.name}` : `Bedding: ${zone?.name}`}
          snap={snap} onSnap={setSnap} onClose={closeSheet} onHeight={onSheetHeight}
          returnFocus={() => selected ? mapEl.current?.querySelector(`.map-pin[data-kind="${selected.kind}"][data-id="${selected.id}"]`) : null}
          focusKey={sheet === 'settings' ? 'settings' : `${selected?.kind}-${selected?.id}`}
          header={sheet === 'settings' ? <><span className="map-eyebrow">Map</span><h2 className="bsheet-name">How the map looks</h2></> : stand ? <StandHeader stand={stand} /> : camera ? <CameraHeader camera={camera} /> : zone ? <ZoneHeader zone={zone} /> : null}>
          {sheet === 'settings' && <MapSheet prefs={prefs} onPrefs={setPrefs} zoom={zoom} baseNote={baseNote}
            catastroNote={catastroErr ? 'Property lines aren’t loading right now. Check the signal.' : null}
            admin={admin} measuring={measure.on} meOn={me.on}
            onMeasure={() => { measure.toggle(); closeSheet() }} onMe={() => { me.toggle(); closeSheet() }}
            onAddStand={() => startEdit({ kind: 'stand', name: '' })}
            onDrawBedding={() => { setSelected(null); startEdit({ kind: 'zone', name: `Bedding ${(data?.zones.length ?? 0) + 1}` }) }}
            onPlace={u => { setSelected({ kind: u.kind, id: u.id }); startEdit({ kind: u.kind, id: u.id, name: u.name }) }}
            unplaced={unplaced}
            terrain={{ needed: !!data && !data.terrain_loaded, busy: terrainBusy, err: terrainErr, onLoad: loadTerrain }} />}
          {stand && <StandBody stand={stand} scentRange={data!.scent_range_m} admin={admin}
            onMove={() => startEdit({ kind: 'stand', id: stand.id, name: stand.name, at: [stand.lon, stand.lat] })}
            onRemove={() => remove('stand', stand.id)} onRename={name => rename(stand.id, name)} />}
          {camera && <CameraBody camera={camera} admin={admin} onMove={() => startEdit({ kind: 'camera', id: camera.id, name: camera.name, at: [camera.lng, camera.lat] })} />}
          {zone && <ZoneBody zone={zone} admin={admin} onRemove={() => remove('zone', zone.id)} />}
        </BottomSheet>}
      </div>
      {editing && <CrosshairEditor map={mapObj} editing={editing} center={center} busy={editBusy} err={editErr} title={editTitle}
        onChange={setEditing} onSave={saveEdit} onCancel={() => { setEditing(null); setEditErr('') }} />}
    </div>
  </div>
}
