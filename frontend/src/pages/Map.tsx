import { FrameCornersIcon } from '@phosphor-icons/react/dist/csr/FrameCorners'
import { MinusIcon } from '@phosphor-icons/react/dist/csr/Minus'
import { NavigationArrowIcon } from '@phosphor-icons/react/dist/csr/NavigationArrow'
import { PlusIcon } from '@phosphor-icons/react/dist/csr/Plus'
import { RulerIcon } from '@phosphor-icons/react/dist/csr/Ruler'
import { StackIcon } from '@phosphor-icons/react/dist/csr/Stack'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { type CSSProperties, useCallback, useEffect, useRef, useState } from 'react'
import { Link, useBlocker, useSearchParams } from 'react-router-dom'
import { api, peekMe, thumbUrl, whoAmI } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { isView, type View } from '../map/activity'
import { ActivityBar, ActivityCard } from '../map/ActivityPanel'
import { BASE_SOURCES, CALLOUT_ZOOM, CATASTRO, baseLabel, baseSource, mapStyle, readPrefs, retryBase, showBase, showCatastro, writePrefs, type BaseId, type MapPrefs } from '../map/basemaps'
import BottomSheet, { type Snap } from '../map/BottomSheet'
import { CameraBody, CameraHeader } from '../map/CameraSheet'
import CrosshairEditor, { Crosshair, useMapCenter, type Editing } from '../map/CrosshairEditor'
import { confirmLeave, hasUnsavedDraft, setUnsavedDraft } from '../map/draftGuard'
import { direction, downwind, isNewCorner, validLngLat, type Camera, type LngLat, type MapData } from '../map/geometry'
import { addLayers, fitEstate, renderLayers, roomFor } from '../map/layers'
import MapFab from '../map/MapFab'
import MapSheet, { type Unplaced } from '../map/MapSheet'
import { PickBody, PickHeader } from '../map/PickSheet'
import { PIN_ICONS, addCallout, declutterLabels, paintBadge, pinsAt, type Pin, type PinRef } from '../map/pins'
import { StandBody, StandHeader, ZoneBody, ZoneHeader } from '../map/PlaceSheet'
import ReplayBar from '../map/ReplayBar'
import ScalePill from '../map/ScalePill'
import { useActivity } from '../map/useActivity'
import { useMeasure } from '../map/useMeasure'
import { useMyPosition } from '../map/useMyPosition'
import { useReplay } from '../map/useReplay'
import '../map/map.css'

type Selection = { kind: 'stand' | 'camera' | 'zone'; id: string }
const SELECTION_KINDS = ['stand', 'camera', 'zone'] as const
// Names under the pins from this zoom in; further out they would pile on top of each other.
const LABEL_ZOOM = 16
// A base map that fails this many tiles with not one getting through is down (or
// blocked on this network), not just slow. One timeout on weak signal is not this.
const FALLBACK_AFTER = 4
// A save that hasn't answered by now isn't going to. The outline stays for Try again.
const SAVE_TIMEOUT_MS = 20_000
// How long a save waits for the map to reload before it lets the drawing bar go.
const RELOAD_WAIT_MS = 8_000
const LOAD_TIMEOUT_MS = 30_000
const ESTATE_CENTER: LngLat = [-1.3608, 39.0947]
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const freshTiles = () => ({ fails: {} as Record<string, number>, loaded: {} as Record<string, number>, errSinceIdle: 0, okSinceErr: 0 })

const initialSelection = (params: URLSearchParams): Selection | null => {
  const kind = SELECTION_KINDS.find(k => params.get(k))
  return kind ? { kind, id: params.get(kind)! } : null
}
type Failure = Error & { offline?: boolean; timeout?: boolean }

export default function MapPage() {
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<Selection | null>(() => initialSelection(params))
  // What the cameras show: their photos (the normal map), where the game is, or a
  // night played back. In the address, so a reload or Back comes back to it.
  const [view, setViewState] = useState<View>(() => { const v = params.get('view'); return isView(v) ? v : 'cameras' })
  const [replayPhoto, setReplayPhoto] = useState<number | null>(null)
  // Bumped on every choice, even the same pin again, so a close in progress is called off.
  const [selKey, setSelKey] = useState(0)
  const [pick, setPick] = useState<PinRef[] | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [snap, setSnap] = useState<Snap>('half')
  const [data, setData] = useState<MapData | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  // Who you are, as the phone knows it, then the shared /auth/me answer (it has a
  // time limit and a saved copy; its own call here had neither).
  const [admin, setAdmin] = useState(() => peekMe()?.role === 'admin')
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
  const [fallbackNoted, setFallbackNoted] = useState(false)
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
  const markers = useRef<Pin[]>([])
  const editRef = useRef(editing); editRef.current = editing
  const busyRef = useRef(editBusy); busyRef.current = editBusy
  const activeBaseRef = useRef(activeBase); activeBaseRef.current = activeBase
  const paramsRef = useRef(params); paramsRef.current = params
  const viewRef = useRef(view); viewRef.current = view
  // Whether a sheet covers the map now (read by the map's own tap handlers).
  const sheetOpenRef = useRef(false)
  const requestId = useRef(0)
  // Cameras opened this visit whose "new" count is cleared here before the server's
  // next answer says so: null while the call is out, then when it answered.
  const seen = useRef(new Map<string, number | null>())
  const [seenTick, setSeenTick] = useState(0)
  const saving = useRef(false)
  const saveCtl = useRef<AbortController | null>(null)
  const lastCorner = useRef({ t: 0, x: 0, y: 0 })
  const labelFrame = useRef(0)
  // Tile health, per source. Kept in a ref: tiles report far too often for state.
  const tiles = useRef(freshTiles())

  const measure = useMeasure(mapObj, ready)
  const measureRef = useRef(measure); measureRef.current = measure
  const me = useMyPosition(mapObj, ready)
  const center = useMapCenter(mapObj, !!editing)
  const act = useActivity(mapObj, ready, view === 'activity')
  const pickActivityRef = useRef(act.pick); pickActivityRef.current = act.pick
  const pickedId = act.picked?.camera_id

  const load = useCallback(async () => {
    const request = ++requestId.current
    const started = Date.now()
    setLoading(true); setErr('')
    try {
      const [next, cams] = await Promise.all([api<MapData>('/map/tonight', { timeoutMs: LOAD_TIMEOUT_MS }), api<Camera[]>('/map/cameras', { timeoutMs: LOAD_TIMEOUT_MS })])
      if (request !== requestId.current) return
      // A count asked for after the camera was marked seen already knows it.
      for (const [id, at] of seen.current) if (at != null && at < started) seen.current.delete(id)
      setData(next); setCameras(cams)
    } catch (e) {
      if (request !== requestId.current) return
      const x = e as Failure
      setErr(x.offline ? 'No signal, so the map didn’t load.' : x.timeout ? 'No answer from the server, so the map didn’t load.' : `Couldn’t load the map. ${x.message}`)
    } finally { if (request === requestId.current) setLoading(false) }
  }, [])
  useEffect(() => { load(); whoAmI().then(u => setAdmin(u.role === 'admin')).catch(() => {}) }, [load])
  useRefetchOnReturn(() => { if (!editRef.current && !busyRef.current) load() }, 120_000)

  function setPrefs(next: MapPrefs) { setPrefsState(next); writePrefs(next) }
  const declutterSoon = useCallback(() => {
    cancelAnimationFrame(labelFrame.current)
    labelFrame.current = requestAnimationFrame(() => declutterLabels(markers.current))
  }, [])

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
    instance.on('rotateend', () => { const b = instance.getBearing(); if (b !== 0 && Math.abs(b) < 12) instance.easeTo({ bearing: 0, duration: 200 }); declutterSoon() })
    instance.on('zoomend', () => { setZoom(Math.round(instance.getZoom() * 10) / 10); declutterSoon() })
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
      // Some of this picture got through, so this is a gap, not an outage: say so now.
      // With nothing through yet, wait for the map to settle before deciding which.
      // A failed tile doesn't repaint the map, so ask for one: 'idle' follows it.
      if (t.loaded[source]) setTileErr(true)
      instance.triggerRepaint()
    })
    instance.on('sourcedata', (e: maplibregl.MapSourceDataEvent) => {
      if (!e.tile || !e.sourceId) return
      const t = tiles.current
      t.loaded[e.sourceId] = (t.loaded[e.sourceId] ?? 0) + 1
      if (e.sourceId === CATASTRO) setCatastroErr(false)
      if (e.sourceId === baseSource(activeBaseRef.current)) t.okSinceErr++
    })
    // Every tile asked for has answered or failed. Failed tiles report at once and good
    // ones only once decoded, so this is the first moment "none got through" is true.
    instance.on('idle', () => {
      const t = tiles.current, base = activeBaseRef.current, source = baseSource(base)
      if (t.errSinceIdle > 0) {
        if (base !== 'world' && !t.loaded[source] && (t.fails[source] ?? 0) >= FALLBACK_AFTER) {
          // The Spanish servers aren't answering here. Show the world imagery and say so.
          setFallbackFrom(base); setFallbackNoted(false); setActiveBase('world'); setTileErr(false)
          tiles.current = freshTiles()
          return
        }
        setTileErr(true)
      } else if (t.okSinceErr > 0) setTileErr(false) // the picture came back by itself
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
        const last = lastCorner.current, now = Date.now(), at: LngLat = [e.lngLat.lng, e.lngLat.lat]
        // The second click of a double click is not a second corner (B-13), nor is a click on a corner.
        if (now - last.t < 350 && Math.hypot(e.point.x - last.x, e.point.y - last.y) < 20) return
        if (!isNewCorner(edit.points, at)) return
        lastCorner.current = { t: now, x: e.point.x, y: e.point.y }
        setEditing({ ...edit, points: [...edit.points, at] })
        return
      }
      if (measureRef.current.on) { measureRef.current.add([e.lngLat.lng, e.lngLat.lat]); return }
      // Activity: a tap on (or next to) a circle reads that camera; anywhere else clears
      // it. With a camera's sheet open, the circle opens that camera's sheet instead.
      if (viewRef.current === 'activity') {
        const { x, y } = e.point, pad = 14
        const hit = instance.queryRenderedFeatures([[x - pad, y - pad], [x + pad, y + pad]], { layers: ['activity-circles', 'activity-quiet', 'activity-checking'] })[0]
        const id = hit?.properties?.id ? String(hit.properties.id) : null
        const pin = id ? markers.current.find(m => m.pin.kind === 'camera' && m.pin.id === id)?.pin : undefined
        if (sheetOpenRef.current) { if (pin) selectRef.current(pin); else chooseRef.current(null) }
        pickActivityRef.current(id)
        return
      }
      if (viewRef.current === 'replay') return
      const feature = instance.getLayer('bedding-fill') ? instance.queryRenderedFeatures(e.point, { layers: ['bedding-fill'] })[0] : undefined
      if (feature?.properties?.id) chooseRef.current({ kind: 'zone', id: String(feature.properties.id) })
      else chooseRef.current(null)
    })
    const resize = new ResizeObserver(() => instance.resize())
    resize.observe(mapEl.current)
    return () => { resize.disconnect(); cancelAnimationFrame(labelFrame.current); markers.current.forEach(m => m.marker.remove()); markers.current = []; instance.remove(); map.current = null; setMapObj(null); fitted.current = false }
    // The map is built once; later preference changes flip layers on the live style.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Base picture and property lines follow the choice without rebuilding the style.
  useEffect(() => { setActiveBase(prefs.base); setFallbackFrom(null); setTileErr(false); tiles.current = freshTiles() }, [prefs.base])
  useEffect(() => { if (ready && map.current) showBase(map.current, activeBase) }, [ready, activeBase])
  useEffect(() => { if (ready && map.current) showCatastro(map.current, prefs.catastro); if (!prefs.catastro) setCatastroErr(false) }, [ready, prefs.catastro])

  /** Try again: ask for the picture's tiles again and nothing else. The style, the drawn layers and `ready` are left alone (B-01, I-11). */
  function retryTiles() {
    const instance = map.current
    if (!instance) return
    tiles.current = freshTiles()
    setTileErr(false)
    // Back from the fallback: the Spanish layer was hidden, so its failed tiles are
    // already gone and showing it again asks for them afresh.
    if (fallbackFrom) { setFallbackFrom(null); setActiveBase(fallbackFrom); showBase(instance, fallbackFrom); return }
    retryBase(instance, activeBase, () => activeBaseRef.current === activeBase)
  }

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    // Tonight's wind and scent say nothing about where the game was: off in Activity and Replay.
    const layers = view === 'cameras' ? prefs.layers : { ...prefs.layers, wind: false, exposure: false, routes: false }
    renderLayers(instance, data, layers, selected?.kind === 'stand' ? selected.id : undefined)
    if (!fitted.current) {
      fitEstate(instance, data, cameras)
      fitted.current = true
      const focus = selected?.kind === 'stand' ? data.stands.find(s => s.id === selected.id) : selected?.kind === 'camera' ? cameras.find(c => c.id === selected.id) : null
      if (focus && validLngLat(focus.lon, focus.lat)) reveal(focus.lon as number, focus.lat as number, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, data, cameras, prefs.layers, selected, view])

  /** Bring a place into the part of the map the sheet doesn't cover. */
  function reveal(lon: number, lat: number, always = false) {
    const instance = map.current, stage = stageRef.current
    if (!instance || !stage) return
    const w = stage.clientWidth, h = stage.clientHeight, wide = w >= 641
    const p = instance.project([lon, lat])
    // Room for the pin and its name above the sheet's middle height, clear of the
    // round buttons at the sides, and room above for a camera's photo.
    const covered = wide ? p.x < 480 && p.y > h * .5 - 90 : p.y > h * .5 - 90
    if (!always && !covered && p.x > 72 && p.x < w - 72 && p.y > 110) return
    instance.easeTo({ center: [lon, lat], zoom: always ? Math.max(16, instance.getZoom()) : instance.getZoom(), offset: wide ? [Math.min(230, w / 4), -h * .1] : [0, -h * .25], duration: always ? 0 : 300 })
  }
  /** Room around the estate for Fit: clear of an open sheet, below it on a phone, beside it on a wider screen. */
  function fitPadding(): number | maplibregl.PaddingOptions {
    const edge = 72
    const wrap = mapEl.current?.getBoundingClientRect(), sheet = mapEl.current?.parentElement?.querySelector('.bsheet')?.getBoundingClientRect()
    if (!wrap || !sheet?.height) return edge
    const room = (px: number, span: number) => Math.max(edge, Math.min(Math.round(px) + 24, span - edge - 80))
    return sheet.width < wrap.width - 2
      ? { top: edge, right: edge, bottom: edge, left: room(sheet.right - wrap.left, wrap.width) }
      : { top: edge, right: edge, left: edge, bottom: room(wrap.bottom - sheet.top, wrap.height) }
  }

  const choose = useCallback((next: Selection | null, sheetSnap: Snap = 'half') => {
    setSelected(next); setPick(null)
    if (next) { setSettingsOpen(false); setSnap(sheetSnap); setSelKey(k => k + 1) }
  }, [])
  const chooseRef = useRef(choose); chooseRef.current = choose
  const select = useCallback((pin: PinRef) => {
    choose({ kind: pin.kind, id: pin.id })
    reveal(pin.lon, pin.lat)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choose])
  const selectRef = useRef(select); selectRef.current = select

  // The open sheet lives in the address, so Back from a camera's photos (or a reload)
  // comes back to it. Replaced, not pushed: tapping pins doesn't fill the history.
  useEffect(() => {
    const current = paramsRef.current, next = new URLSearchParams(current)
    for (const k of SELECTION_KINDS) next.delete(k)
    if (selected) next.set(selected.kind, selected.id)
    if (view === 'cameras') next.delete('view'); else next.set('view', view)
    if (next.toString() !== current.toString()) setParams(next, { replace: true })
  }, [selected, view, setParams])

  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || !data) return
    markers.current.forEach(m => m.marker.remove()); markers.current = []
    const add = (pin: PinRef) => {
      const el = document.createElement('button')
      el.dataset.kind = pin.kind; el.dataset.id = pin.id
      el.type = 'button'; el.className = `map-pin map-pin--${pin.kind}`
      el.setAttribute('aria-label', `${pin.kind === 'stand' ? 'Stand' : 'Camera'}: ${pin.name}`)
      const icon = document.createElement('span'); icon.className = 'map-pin-icon'; icon.innerHTML = PIN_ICONS[pin.kind]
      const label = document.createElement('span'); label.className = 'map-pin-label'; label.textContent = pin.name
      el.append(icon, label)
      if (pin.photo) addCallout(el, pin.photo)
      el.addEventListener('click', e => {
        e.stopPropagation()
        if (editRef.current || measureRef.current.on) return
        // Activity reads a camera's circle in a card; the camera's sheet is one tap on from there.
        if (viewRef.current === 'activity') {
          if (pin.kind !== 'camera') return
          if (sheetOpenRef.current) selectRef.current(pin)
          pickActivityRef.current(pin.id)
          return
        }
        if (viewRef.current === 'replay') return
        // A camera usually sits by a stand, so at estate zoom their pins overlap. A tap
        // on more than one asks which; a key press (no pointer) means this pin. A
        // camera's photo stands above its pin and can cover a stand close by when
        // zoomed in, so a tap on it is that camera plus whatever pin is under it.
        const onPhoto = (e.target as HTMLElement).closest('.map-callout')
        const here = e.detail ? pinsAt(markers.current, e.clientX, e.clientY) : []
        if (onPhoto && here.length && !here.some(p => p.kind === pin.kind && p.id === pin.id)) here.unshift(pin)
        if (here.length > 1) { setSelected(null); setSettingsOpen(false); setPick(here); setSnap('half'); setSelKey(k => k + 1) }
        else selectRef.current(pin)
      })
      markers.current.push({ marker: new maplibregl.Marker({ element: el }).setLngLat([pin.lon, pin.lat]).addTo(instance), pin })
    }
    // Cameras go on last, so where a pin overlaps they are on top: they're what the team opens the map for.
    data.stands.forEach(s => { if (validLngLat(s.lon, s.lat)) add({ kind: 'stand', id: s.id, name: s.name, lon: s.lon!, lat: s.lat! }) })
    cameras.forEach(c => { if (validLngLat(c.lon, c.lat)) add({ kind: 'camera', id: c.id, name: c.name, lon: c.lon!, lat: c.lat!, photo: c.latest ? thumbUrl(c.latest.image_id) : null }) })
  }, [ready, data, cameras])

  // Each camera's "new" count: nothing for a camera opened since the counts came in.
  useEffect(() => {
    for (const { marker, pin } of markers.current) {
      const cam = pin.kind === 'camera' ? cameras.find(c => c.id === pin.id) : null
      if (cam) paintBadge(marker.getElement(), seen.current.has(cam.id) ? 0 : cam.new_count, cam.name)
    }
  }, [ready, data, cameras, seenTick])

  // Activity and Replay: every placed camera in view above the docked bar, with room
  // round each for its circle or its photo (a photo pops up above its camera).
  const placedKey = cameras.filter(c => validLngLat(c.lon, c.lat)).map(c => `${c.id}:${c.lon},${c.lat}`).join('|')
  useEffect(() => {
    const instance = map.current
    if (!instance || !ready || view === 'cameras' || !placedKey) return
    const frame = requestAnimationFrame(() => {
      instance.resize()
      const pts = placedKey.split('|').map(p => p.split(':')[1].split(',').map(Number) as LngLat)
      const { clientWidth: w, clientHeight: h } = instance.getCanvas()
      if (w < 120 || h < 80) return // a sliver of map: leave it where it is
      // Photos pop up above their cameras in Replay, so more room there; a small
      // map gives up some of it rather than zoom out to nothing.
      const side = Math.min(view === 'replay' ? 96 : 64, w * .2)
      const padding = { top: Math.min(view === 'replay' ? 96 : 60, h * .25), bottom: Math.min(40, h * .1), left: side, right: Math.max(side, Math.min(72, w * .2)) }
      instance.fitBounds([[Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1]))], [Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1]))]],
        { padding: roomFor(instance, padding), maxZoom: 16, duration: 300 })
    })
    return () => cancelAnimationFrame(frame)
  }, [view, ready, placedKey])
  // The camera being read stays in sight above its card.
  useEffect(() => {
    if (view !== 'activity' || !pickedId) return
    const frame = requestAnimationFrame(() => {
      const instance = map.current, c = cameras.find(x => x.id === pickedId)
      const card = stageRef.current?.querySelector<HTMLElement>('.act-card')
      if (!instance || !c || !card || !validLngLat(c.lon, c.lat)) return
      const covered = card.offsetHeight + 24, p = instance.project([c.lon!, c.lat!]), h = instance.getCanvas().clientHeight
      if (p.y > 70 && p.y < h - covered - 30) return
      instance.easeTo({ center: [c.lon!, c.lat!], offset: [0, -covered / 2], duration: 300 })
    })
    return () => cancelAnimationFrame(frame)
    // Only when another camera is chosen: the map refreshing mustn't pull it back.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, pickedId])

  // Opening a camera's sheet marks its photos seen, for this person only.
  const openCamera = selected?.kind === 'camera' ? selected.id : null
  useEffect(() => {
    if (!openCamera) return
    const marks = seen.current
    marks.set(openCamera, null); setSeenTick(t => t + 1)
    // Failed or not, the next load after this answers with the server's own count.
    const answered = () => { if (marks.has(openCamera)) marks.set(openCamera, Date.now()) }
    api(`/cameras/${openCamera}/seen`, { method: 'POST', timeoutMs: SAVE_TIMEOUT_MS }).then(answered, answered)
  }, [openCamera, selKey])

  useEffect(() => {
    for (const { marker, pin } of markers.current) {
      const el = marker.getElement() as HTMLButtonElement
      // In Activity the chosen camera is the one whose circle is being read. Stands
      // are only landmarks there, and in Replay nothing on the map but its photos is.
      const active = view === 'activity' ? pin.kind === 'camera' && pin.id === pickedId : pin.id === selected?.id && pin.kind === selected?.kind
      const inert = !!editing || measure.on || view === 'replay' || (view === 'activity' && pin.kind === 'stand')
      el.classList.toggle('is-selected', active)
      el.setAttribute('aria-pressed', String(active))
      el.disabled = inert
      el.style.pointerEvents = inert ? 'none' : ''
    }
  }, [ready, data, cameras, selected, editing, measure.on, view, pickedId])
  // Names that would land on another pin stay hidden (after the pins above are in place).
  useEffect(() => { declutterSoon() }, [ready, data, cameras, selected, zoom, prefs.bigPins, prefs.layers.photos, declutterSoon])

  // While drawing, a double tap must not zoom and add a corner at once (B-13).
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (editing) instance.doubleClickZoom.disable(); else instance.doubleClickZoom.enable()
  }, [editing != null])
  const draftWhat = editing?.kind === 'zone' && editing.points.length ? 'this bedding outline' : editing && !editing.id && editing.name.trim() ? 'this stand' : ''
  useEffect(() => {
    setUnsavedDraft(draftWhat)
    if (!draftWhat) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [draftWhat])
  useEffect(() => () => setUnsavedDraft(''), [])
  // Leaving with an unsaved outline asks first, whichever way you leave: a tab, the
  // browser's Back, or the phone's back gesture (B-12).
  const blocker = useBlocker(({ currentLocation, nextLocation }) => hasUnsavedDraft() && currentLocation.pathname !== nextLocation.pathname)
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    if (confirmLeave()) blocker.proceed(); else blocker.reset()
  }, [blocker])
  useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(t) }, [notice])

  // ── placing and drawing ──
  function startEdit(next: Omit<Editing, 'step' | 'points'> & { at?: [number | null | undefined, number | null | undefined] }) {
    const instance = map.current
    const [lon, lat] = next.at ?? []
    if (instance && validLngLat(lon, lat)) instance.jumpTo({ center: [lon as number, lat as number], zoom: Math.max(16, instance.getZoom()) })
    measure.stop(); setSettingsOpen(false); setPick(null); setEditErr(''); setViewState('cameras')
    setEditing({ kind: next.kind, id: next.id, name: next.name, points: [], step: 'place' })
  }
  async function saveEdit(at: LngLat | null) {
    const e = editRef.current
    if (!e || saving.current || !e.name.trim()) return
    // The live centre, not the last rendered one: the cross is wherever the map is now.
    const live = map.current?.getCenter()
    const point: LngLat | null = live ? [live.lng, live.lat] : at
    if (e.kind === 'zone' ? e.points.length < 3 : !point) return
    // Cancel aborts this; the timeout gives up on a connection that never answers.
    const ctl = new AbortController(); saveCtl.current = ctl
    const send = (body: unknown, method: string) => ({ method, body: JSON.stringify(body), signal: ctl.signal, timeoutMs: SAVE_TIMEOUT_MS })
    saving.current = true; setEditBusy(true); setEditErr('')
    try {
      let created: { id: string } | undefined
      if (e.kind === 'zone') await api('/zones', send({ name: e.name.trim(), kind: 'bedding', polygon: { type: 'Polygon', coordinates: [[...e.points, e.points[0]]] } }, 'POST'))
      else if (e.kind === 'camera') await api(`/cameras/${e.id}/location`, send({ lat: point![1], lng: point![0] }, 'PUT'))
      else if (e.id) await api(`/stands/${e.id}`, send({ lat: point![1], lon: point![0] }, 'PATCH'))
      else created = await api<{ id: string }>('/stands', send({ name: e.name.trim(), lat: point![1], lon: point![0] }, 'POST'))
      // The draft stays until the new positions are in, so the pin never jumps back (B-17).
      // A reload that hangs doesn't hold the bar, though: the save itself is done.
      await Promise.race([load(), wait(RELOAD_WAIT_MS)])
      setEditing(null)
      if (created?.id) choose({ kind: 'stand', id: created.id }, 'peek')
      else if (e.id) setSnap('peek')
      setNotice(e.kind === 'zone' ? 'Bedding saved.' : 'Saved.')
    } catch (x) {
      // Cancelled: the hunter has already left the drawing bar.
      if (ctl.signal.aborted) return
      const kept = e.kind === 'zone' ? 'Your outline is kept.' : 'It isn’t saved yet.'
      setEditErr((x as Failure).timeout ? `No answer from the server. ${kept}` : `That didn’t save. ${(x as Error).message}`)
    } finally {
      saving.current = false; setEditBusy(false)
      if (saveCtl.current === ctl) saveCtl.current = null
    }
  }
  function cancelEdit() {
    saveCtl.current?.abort()
    setEditing(null); setEditErr('')
  }
  async function remove(kind: 'stand' | 'zone', id: string) {
    try {
      await api(`/${kind === 'stand' ? 'stands' : 'zones'}/${id}`, { method: 'DELETE', timeoutMs: SAVE_TIMEOUT_MS })
    } catch (x) {
      const status = (x as Error & { status?: number }).status
      if (kind === 'stand' && status === 409) throw Object.assign(new Error('This stand has sit history, so it can’t be removed. Rename it instead.'), { final: true })
      throw new Error(`That didn’t remove. ${(x as Error).message}`)
    }
    // Said once the map shows it, so the pin never lingers under 'Removed'.
    await load(); setSelected(null); setNotice('Removed from the map.')
  }
  async function rename(id: string, name: string) {
    try { await api(`/stands/${id}`, { method: 'PATCH', body: JSON.stringify({ name }), timeoutMs: SAVE_TIMEOUT_MS }) }
    catch (x) { throw new Error(`That didn’t save. ${(x as Error).message}`) }
    await load(); setNotice('Renamed.')
  }
  async function renameCamera(id: string, name: string) {
    try { await api(`/cameras/${id}/name`, { method: 'PATCH', body: JSON.stringify({ name }), timeoutMs: SAVE_TIMEOUT_MS }) }
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
  // Nothing loaded is not the same as calm air: never state a verdict without the forecast.
  const windWord = !data ? (loading ? 'Checking…' : 'Wind not loaded') : from != null ? `From the ${direction(from)}` : speed == null ? 'No wind forecast' : 'Too light to call'
  const unplaced: Unplaced[] = [
    ...(data?.stands ?? []).filter(s => !validLngLat(s.lon, s.lat)).map(s => ({ kind: 'stand' as const, id: s.id, name: s.name })),
    ...cameras.filter(c => !validLngLat(c.lon, c.lat)).map(c => ({ kind: 'camera' as const, id: c.id, name: c.name })),
  ]
  const placedCount = (data?.stands.length ?? 0) + cameras.length - unplaced.length
  const emptyEstate = !!data && !editing && placedCount === 0 && !data.zones.length
  const sheet = editing ? null : (stand || camera || zone) ? 'place' : pick ? 'pick' : settingsOpen ? 'settings' : null
  sheetOpenRef.current = !!sheet
  const closeSheet = () => { setSelected(null); setSettingsOpen(false); setPick(null) }
  // Activity and Replay dock their controls under the map; a sheet opened over the
  // map (a camera, the Map sheet) puts them away until it closes.
  const modeBar = view !== 'cameras' && !editing && !sheet
  const replay = useReplay(mapObj, ready, view === 'replay', modeBar, cameras, setReplayPhoto)
  function setView(next: View) {
    setViewState(next); setSelected(null); setPick(null); setSettingsOpen(false); setReplayPhoto(null); setWindOpen(false)
    if (next !== 'activity') act.pick(null)
  }
  function openCameraSheet(id: string) {
    const c = cameras.find(x => x.id === id)
    if (c && validLngLat(c.lon, c.lat)) select({ kind: 'camera', id, name: c.name, lon: c.lon!, lat: c.lat! })
    else choose({ kind: 'camera', id })
  }
  // Nothing to draw, in words. Photos still waiting for the detector are not a
  // camera that wasn't working: at dawn last night's newest photos often are.
  const activityEmpty = (() => {
    const a = act.data
    if (view !== 'activity' || !a || act.loading || act.err) return ''
    const checking = a.cameras.filter(c => c.checking_nights > 0).length, one = a.nights === 1
    if (a.cameras.every(c => !c.watched_nights)) {
      if (checking) return `Still checking ${one ? 'last night’s' : 'the'} photos. Look again in a few minutes.`
      if (a.cameras.some(c => c.unreadable_nights)) return `Nothing to show: ${one ? 'last night’s' : 'the'} photos couldn’t all be checked for animals.`
      return `No camera was working ${one ? 'last night' : 'in this period'}, so there is nothing to show.`
    }
    if (a.cameras.every(c => !c.visits)) {
      if (checking) return `No visits so far. Still checking the photos from ${checking === 1 ? '1 camera' : `${checking} cameras`}.`
      return one && a.so_far ? 'No visits last night so far.' : 'No visits in this period.'
    }
    return ''
  })()
  const onSheetHeight = useCallback((px: number) => {
    const stage = stageRef.current
    if (!stage) return
    stage.style.setProperty('--sheet-h', `${px}px`)
    stage.dataset.sheet = px > stage.clientHeight * .7 ? 'tall' : px > 0 ? 'open' : ''
  }, [])
  const baseNote = fallbackFrom ? `${baseLabel(fallbackFrom)} from IGN isn’t loading here, so this is ${baseLabel('world')} for now. Tap ${baseLabel(fallbackFrom)} to try it again.` : null
  const tileNotice = tileErr ? 'Part of the map picture didn’t load. Your stands and cameras are still on it.'
    : fallbackFrom && !fallbackNoted ? `${baseLabel(fallbackFrom)} isn’t loading, so this is ${baseLabel('world')}.` : ''
  const editTitle = editing ? editing.kind === 'zone' ? 'Draw bedding' : editing.id ? `Move ${editing.name}` : 'New stand' : ''

  if (fatal) return <div className="map-page map-page--fatal">
    <h1 className="page-title">Map</h1>
    <div className="map-message map-message--error" role="alert">{fatal}</div>
    <div className="map-actions"><Link className="map-button" to="/stands">Stands</Link><Link className="map-button" to="/cameras">Cameras</Link></div>
  </div>

  return <div className="map-page" style={{ '--pin-scale': prefs.bigPins ? 1.25 : 1 } as CSSProperties}>
    <h1 className="sr-only">Map</h1>
    {/* Tonight's wind says nothing about where the game was, and the views that show
        that turn the wind off: the map gets the room instead. */}
    {view === 'cameras' && <button type="button" className="map-windbar" aria-expanded={windOpen} aria-controls="map-wind-more" onClick={() => setWindOpen(v => !v)}>
      <span className="wind-direction" aria-hidden="true"><svg viewBox="0 0 40 40" style={{ transform: from == null ? undefined : `rotate(${downwind(from) - bearing}deg)` }}><circle cx="20" cy="20" r="18" />{from != null && <path d="M20 29V11m-6 6 6-6 6 6" />}</svg></span>
      <span className="map-wind-reading">
        <span>{air?.source === 'katabatic' ? 'Calm evening. Cold air sliding downhill' : air?.source === 'anabatic' ? 'Calm and sunny. Air drifting uphill' : 'Wind tonight'}</span>
        <strong>{windWord}</strong>
        {from != null && <em>Scent goes {direction(downwind(from))}</em>}
      </span>
      <span className="map-wind-speed"><strong>{speed == null || !data ? '—' : Math.round(speed)}</strong><span>km/h</span></span>
      <span className="map-wind-chevron" aria-hidden="true">{windOpen ? '▴' : '▾'}</span>
    </button>}
    <div className="map-stage" ref={stageRef} data-editing={editing ? 'true' : undefined} data-labels={zoom >= LABEL_ZOOM ? 'on' : undefined}
      data-view={view === 'cameras' ? undefined : view}
      data-callouts={!prefs.layers.photos || view !== 'cameras' ? undefined : zoom >= CALLOUT_ZOOM ? 'on' : 'dots'}>
      <div className="map-canvas-wrap">
        <div ref={mapEl} className="map-canvas" aria-label="Estate map. Drag to move, pinch to zoom." />
        {windOpen && view === 'cameras' && <div id="map-wind-more" className="map-wind-more">
          {!data && <p>{loading ? 'Getting tonight’s wind…' : 'The wind comes with the map. It shows once the map loads.'}</p>}
          {air?.text && <p>{air.text}</p>}
          <p>Arrows show where scent goes from each stand. Tap a stand to see how far it carries.</p>
          <p className="map-caveat">An indication only. Wind near the ground swirls.</p>
        </div>}
        <ScalePill map={mapObj} />
        <div className="map-notices">
          {err && <div className="map-pill map-pill--error" role="alert"><span>{err}</span><button type="button" onClick={load} disabled={loading}>Try again</button></div>}
          {tileNotice && <div className="map-pill" role="status"><span>{tileNotice}</span><button type="button" onClick={retryTiles}>Try again</button>
            {!tileErr && <button type="button" aria-label="OK, keep this map" onClick={() => setFallbackNoted(true)}>OK</button>}</div>}
          {emptyEstate && <div className="map-pill map-pill--empty" role="status">
            <span>{data.stands.length + cameras.length === 0
              ? admin ? 'Nothing on the map yet. Add a stand here, and connect cameras in Settings.' : 'Nothing on the map yet. An admin adds stands here and connects cameras in Settings.'
              : admin ? 'Your stands and cameras aren’t placed on the map yet.' : 'The stands and cameras aren’t placed on the map yet. An admin can place them.'}</span>
            {admin && <span className="map-pill-actions">
              {data.stands.length + cameras.length === 0
                ? <><button type="button" onClick={() => startEdit({ kind: 'stand', name: '' })}>Add a stand</button><Link to="/settings">Settings</Link></>
                : <button type="button" onClick={() => { choose(null); setSettingsOpen(true); setSnap('full') }}>Place them</button>}
            </span>}
          </div>}
          {measure.on && <div className="map-pill map-pill--measure" role="status">
            <span>{measure.result ?? (measure.points.length ? 'Now tap the second point.' : 'Tap two points to measure.')}</span>
            {measure.result && <button type="button" onClick={measure.clear}>Clear</button>}
            <button type="button" onClick={measure.stop}>Done</button>
          </div>}
          {notice && <div className="map-pill" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice('')}>OK</button></div>}
          {view === 'activity' && act.err && <div className="map-pill map-pill--error" role="alert"><span>{act.err}</span><button type="button" onClick={act.reload} disabled={act.loading}>Try again</button></div>}
          {view === 'activity' && act.loading && <div className="map-pill" role="status"><span>{act.data ? 'Updating the circles…' : 'Loading activity…'}</span></div>}
          {activityEmpty && <div className="map-pill map-pill--empty" role="status"><span>{activityEmpty}</span></div>}
          {view === 'replay' && replay.data && !replay.visits.length && <div className="map-pill map-pill--empty" role="status"><span>Nothing came past a camera that night.</span></div>}
        </div>
        {!ready && <div className="map-loading" role="status">Loading map…</div>}
        {modeBar && view === 'activity' && act.picked && act.data && <ActivityCard camera={act.picked} data={act.data}
          onOpen={() => openCameraSheet(act.picked!.camera_id)} onClose={() => act.pick(null)} onHeight={onSheetHeight} />}

        {!editing && <div className="map-fabs map-fabs--right">
          <MapFab label="Map type, layers and tools" pressed={settingsOpen} onClick={() => { setSelected(null); setPick(null); setSettingsOpen(v => !v); setSnap('half') }}><StackIcon size={22} /></MapFab>
          <MapFab label="Point the map north" onClick={() => map.current?.easeTo({ bearing: 0, pitch: 0, duration: 300 })}>
            <svg className="map-north" viewBox="0 0 24 24" aria-hidden="true" style={{ transform: `rotate(${-bearing}deg)` }}>
              <path className="map-north-n" d="M12 3.5 15 12H9z" /><path className="map-north-s" d="M12 20.5 9 12h6z" /><path className="map-north-tick" d="M12 1v3" />
            </svg>
          </MapFab>
          <MapFab label="Fit the estate" disabled={!data || !ready} onClick={() => { if (map.current && data) fitEstate(map.current, data, cameras, 300, fitPadding()) }}><FrameCornersIcon size={22} /></MapFab>
          {/* Zoom with a glove on: pinching through a glove, or with one hand on a
              rifle, doesn't work. */}
          <MapFab label="Zoom in" disabled={!ready} onClick={() => map.current?.zoomIn({ duration: 250 })}><PlusIcon size={22} weight="bold" /></MapFab>
          <MapFab label="Zoom out" disabled={!ready} onClick={() => map.current?.zoomOut({ duration: 250 })}><MinusIcon size={22} weight="bold" /></MapFab>
        </div>}
        {!editing && <div className="map-fabs map-fabs--left">
          {me.message && <div className="map-pill map-pill--side" role="status"><span>{me.message}</span><button type="button" aria-label="Dismiss" onClick={me.clearMessage}>OK</button></div>}
          <MapFab label={measure.on ? 'Stop measuring' : 'Measure a distance'} pressed={measure.on} onClick={() => { measure.toggle(); closeSheet() }}><RulerIcon size={22} /></MapFab>
          <MapFab label={me.on ? 'Hide where I am' : 'Show where I am'} pressed={me.on} onClick={me.toggle}><NavigationArrowIcon size={22} /></MapFab>
        </div>}
        {editing && <Crosshair editing={editing} center={center} />}

        {sheet && <BottomSheet
          label={sheet === 'settings' ? 'Map settings' : sheet === 'pick' ? 'Which one?' : stand ? `Stand: ${stand.name}` : camera ? `Camera: ${camera.name}` : `Bedding: ${zone?.name}`}
          snap={snap} onSnap={setSnap} onClose={closeSheet} onHeight={onSheetHeight}
          returnFocus={() => selected ? mapEl.current?.querySelector(`.map-pin[data-kind="${selected.kind}"][data-id="${selected.id}"]`) : null}
          focusKey={sheet === 'settings' ? 'settings' : `${sheet}-${selKey}`}
          header={sheet === 'settings' ? <><span className="map-eyebrow">Map</span><h2 className="bsheet-name">How the map looks</h2></>
            : sheet === 'pick' ? <PickHeader count={pick!.length} />
              : stand ? <StandHeader stand={stand} /> : camera ? <CameraHeader camera={camera} /> : zone ? <ZoneHeader zone={zone} /> : null}>
          {sheet === 'settings' && <MapSheet view={view} onView={setView} prefs={prefs} onPrefs={setPrefs} onRetryBase={() => { if (fallbackFrom || tileErr) retryTiles() }} zoom={zoom} baseNote={baseNote}
            catastroNote={catastroErr ? 'Property lines aren’t loading right now. Check the signal.' : null}
            admin={admin} measuring={measure.on} meOn={me.on}
            onMeasure={() => { measure.toggle(); closeSheet() }} onMe={() => { me.toggle(); closeSheet() }}
            onAddStand={() => startEdit({ kind: 'stand', name: '' })}
            onDrawBedding={() => { setSelected(null); startEdit({ kind: 'zone', name: `Bedding ${(data?.zones.length ?? 0) + 1}` }) }}
            onPlace={u => { setSelected({ kind: u.kind, id: u.id }); startEdit({ kind: u.kind, id: u.id, name: u.name }) }}
            unplaced={unplaced}
            terrain={{ needed: !!data && !data.terrain_loaded, busy: terrainBusy, err: terrainErr, onLoad: loadTerrain }} />}
          {sheet === 'pick' && <PickBody pins={pick!} onPick={select} />}
          {stand && <StandBody stand={stand} scentRange={data!.scent_range_m} admin={admin}
            onMove={() => startEdit({ kind: 'stand', id: stand.id, name: stand.name, at: [stand.lon, stand.lat] })}
            onRemove={() => remove('stand', stand.id)} onRename={name => rename(stand.id, name)} />}
          {camera && <CameraBody camera={camera} admin={admin} onRename={name => renameCamera(camera.id, name)}
            onAlerts={(alerts, enabled) => setCameras(cs => cs.map(c => c.id === camera.id ? { ...c, alerts, alerts_enabled: enabled } : c))}
            onMove={() => startEdit({ kind: 'camera', id: camera.id, name: camera.name, at: [camera.lon, camera.lat] })} />}
          {zone && <ZoneBody zone={zone} admin={admin} onRemove={() => remove('zone', zone.id)} />}
        </BottomSheet>}
      </div>
      {editing && <CrosshairEditor map={mapObj} editing={editing} center={center} busy={editBusy} err={editErr} title={editTitle}
        onChange={setEditing} onSave={saveEdit} onCancel={cancelEdit} />}
      {modeBar && view === 'activity' && <ActivityBar filters={act.filters} onFilters={f => { act.setFilters(f) }} data={act.data} onClose={() => setView('cameras')}
        cardOpen={!!(act.picked && act.data)} />}
      {modeBar && view === 'replay' && <ReplayBar replay={replay} cameras={cameras} photo={replayPhoto} onPhoto={setReplayPhoto} onClose={() => setView('cameras')} />}
    </div>
  </div>
}
