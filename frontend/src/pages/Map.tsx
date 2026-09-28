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
import { ageLabel, api, fromEarlierNight, getFresh, noAnswer, noAnswerWords, peek, peekMe, savedCopy, thumbUrl, whenLabel, whoAmI, type Got, type StaleWhy } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { type Key, fmtTime, t, useLang } from '../i18n'
import { isView, type View } from '../map/activity'
import { ActivityBar, ActivityCard } from '../map/ActivityPanel'
import { BASE_SOURCES, CALLOUT_ZOOM, CATASTRO, baseLabel, baseSource, mapStyle, readPrefs, retryBase, showBase, showCatastro, writePrefs, type BaseId, type MapPrefs } from '../map/basemaps'
import BottomSheet, { type Snap } from '../map/BottomSheet'
import { CameraBody, CameraHeader } from '../map/CameraSheet'
import CrosshairEditor, { Crosshair, useMapCenter, type Editing } from '../map/CrosshairEditor'
import { confirmLeave, hasUnsavedDraft, setUnsavedDraft } from '../map/draftGuard'
import { directionFrom, downwind, scentTowards, isNewCorner, validLngLat, type Camera, type LikelyPath, type LngLat, type MapData } from '../map/geometry'
import { addLayers, estateBounds, fitEstate, renderBox, renderLayers, renderPaths, roomFor } from '../map/layers'
import MapFab from '../map/MapFab'
import MapSheet, { type Unplaced } from '../map/MapSheet'
import { coverage, readSaved, stopDownload, useDownload, type Box, type Saved } from '../map/offline'
import { progressWords } from '../map/OfflinePanel'
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

/** MapLibre's own words (what a screen reader calls the map, a mark on it, the
 *  credits button), in the language on screen: its built-in ones are English. */
const mapWords = (): Record<string, string> => ({
  'Map.Title': t('nav.map'),
  'Marker.Title': t('mapPage.marker'),
  'AttributionControl.ToggleAttribution': t('mapPage.credits'),
  'AttributionControl.MapFeedback': t('mapPage.feedback'),
})

type Selection = { kind: 'stand' | 'camera' | 'zone'; id: string }
const SELECTION_KINDS = ['stand', 'camera', 'zone'] as const
// Names under the pins from this zoom in; further out they would pile on top of each other.
const LABEL_ZOOM = 16
// A base map that fails this many tiles with not one getting through is down (or
// blocked on this network), not just slow. One timeout on weak signal is not this.
const FALLBACK_AFTER = 4
const FALLBACK_GRACE_MS = 1200
// A save that hasn't answered by now isn't going to. The outline stays for Try again.
const SAVE_TIMEOUT_MS = 20_000
// How long a save waits for the map to reload before it lets the drawing bar go.
const RELOAD_WAIT_MS = 8_000
const LOAD_TIMEOUT_MS = 30_000
const ESTATE_CENTER: LngLat = [-1.3608, 39.0947]
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))
const freshTiles = () => ({ fails: {} as Record<string, number>, loaded: {} as Record<string, number>, errSinceIdle: 0, okSinceErr: 0 })

// How long the hill shape is waited for after the button, asking every few seconds.
const TERRAIN_WAIT_MS = 3 * 60_000
const TERRAIN_POLL_MS = 3_000
type TerrainStatus = { state: 'none' | 'loading' | 'loaded' | 'failed'; error: string | null }

/**
 * A saved copy of the map from an earlier night (no signal since) keeps its stands,
 * cameras and bedding, and loses its wind: that was the wind for that night, and a
 * hunter reading "Wind is right" off it tonight would be misled.
 */
function withoutWind(d: MapData): MapData {
  return {
    ...d,
    conditions: { wind_dir_deg: null, wind_speed_kmh: null },
    airflow: { source: 'unknown', wind_dir_deg: null, wind_speed_kmh: null },
    stands: d.stands.map(s => ({ ...s, wind: { status: 'no_wind_data', text: t('mapPage.earlierWind') } })),
    safe_ground: { status: 'no_wind_data', cells: [] },
  }
}
const forTonight = (got: Got<MapData>) => fromEarlierNight(got.at) ? withoutWind(got.data) : got.data

/** Pictures failed with no signal: why, against the map saved on this phone. */
function savedWords(saved: Saved, where: ReturnType<typeof coverage> | 'other' | null): string {
  if (where === 'close') return t('mapPage.tooClose')
  if (where === 'partial') return t('mapPage.partNotSaved')
  if (where === 'other') return t('mapPage.otherBase', { base: baseLabel(saved.base) })
  if (where === 'inside') return t('mapPage.pictureGap')
  return t('mapPage.pastEstate')
}

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
  // What the phone has from before paints at once; the answer replaces it (B-06).
  const [data, setData] = useState<MapData | null>(() => { const got = peek<MapData>('/map/tonight'); return got ? forTonight(got) : null })
  const [cameras, setCameras] = useState<Camera[]>(() => peek<Camera[]>('/map/cameras')?.data ?? [])
  // A saved copy on screen: when it is from, and why (none yet: the answer is on its way).
  const [dataAge, setDataAge] = useState<{ at: string; why?: StaleWhy } | null>(() => { const got = peek<MapData>('/map/tonight'); return got ? { at: got.at } : null })
  const [savedEstate, setSavedEstate] = useState<Saved | null>(null)
  const [paths, setPaths] = useState<LikelyPath[] | null>(null)
  const [pathsErr, setPathsErr] = useState('')
  const [estateBox, setEstateBox] = useState<Box | null>(null)
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
  // What it fell back to: the base saved on this phone when there is one, else Esri's.
  const [fallbackTo, setFallbackTo] = useState<BaseId>('world')
  const [fallbackNoted, setFallbackNoted] = useState(false)
  const [tileErr, setTileErr] = useState(false)
  // Where the view is against the map saved on this phone when pictures failed:
  // said instead of "didn't load" when there is no signal.
  const [tileWhere, setTileWhere] = useState<ReturnType<typeof coverage> | 'other' | null>(null)
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
  const savedRef = useRef<Saved | null>(null); savedRef.current = savedEstate
  // With no signal Esri's pictures can't come either, so the map never falls back to them.
  const noSignalRef = useRef(false); noSignalRef.current = dataAge?.why === 'offline'
  // Base maps given up on since a picture last loaded (or Try again). One is never gone
  // back to, so two that both fail don't swap for ever (review R4FE-3).
  const tried = useRef(new Set<BaseId>())
  const alive = useRef(true)
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
  const fallbackTimer = useRef(0)
  // Tile health, per source. Kept in a ref: tiles report far too often for state.
  const tiles = useRef(freshTiles())

  // "Download the estate" runs on whatever the screen shows; the map says how far it is.
  const job = useDownload()
  const lastOutcome = useRef(job.outcome)
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
    // Each on its own, and each falling back to what the phone saved: the cameras
    // failing must not take the stands down with them, nor no signal the whole map.
    const [tonight, cams] = await Promise.allSettled([
      getFresh<MapData>('/map/tonight', { timeoutMs: LOAD_TIMEOUT_MS, save: true }),
      getFresh<Camera[]>('/map/cameras', { timeoutMs: LOAD_TIMEOUT_MS, save: true }),
    ])
    if (request !== requestId.current) return
    // A count asked for after the camera was marked seen already knows it.
    for (const [id, at] of seen.current) if (at != null && at < started) seen.current.delete(id)
    if (tonight.status === 'fulfilled') setData(forTonight(tonight.value))
    if (cams.status === 'fulfilled') setCameras(cams.value.data)
    const stale = [tonight, cams].flatMap(r => r.status === 'fulfilled' && r.value.stale ? [r.value] : [])
    setDataAge(stale.length ? { at: stale.map(g => g.at).sort()[0], why: stale[0].why } : null)
    const failed = [tonight, cams].find((r): r is PromiseRejectedResult => r.status === 'rejected')
    if (failed) {
      const x = failed.reason as Failure
      const what: Key = tonight.status === 'rejected' && cams.status === 'rejected' ? 'mapPage.theMap' : tonight.status === 'rejected' ? 'mapPage.theStands' : 'mapPage.theCameras'
      setErr(x.offline ? t('replay.noSignal', { what: t(what) }) : x.timeout ? t('replay.noAnswer', { what: t(what) }) : t('replay.couldnt', { what: t(what), why: x.message }))
    }
    setLoading(false)
  }, [])
  useEffect(() => {
    alive.current = true
    load(); whoAmI().then(u => setAdmin(u.role === 'admin')).catch(() => {})
    return () => { alive.current = false }
  }, [load])
  // What is saved on the phone, read again whenever a download writes its note or ends.
  useEffect(() => {
    let live = true
    readSaved().then(s => { if (live) setSavedEstate(s) })
    return () => { live = false }
  }, [job.version])
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
    // Opened on the estate as the phone last saw it, so the first pictures asked for
    // are the estate's (the ones a phone with no signal has saved), not a wider view's.
    // Only with room for the padding: fitting a sliver of map asks for a camera at NaN.
    const roomy = mapEl.current.clientWidth > 240 && mapEl.current.clientHeight > 240
    const start = data && roomy ? estateBounds(data, cameras) : null
    const opening = start ? { bounds: start, fitBoundsOptions: { padding: 72, maxZoom: 16 } } : { center: ESTATE_CENTER, zoom: 14 }
    try {
      instance = new maplibregl.Map({ container: mapEl.current, style: mapStyle(prefs), ...opening, maxZoom: 20, maxPitch: 0, attributionControl: false, locale: mapWords() })
    } catch { setFatal(t('mapPage.fatal')); return }
    map.current = instance
    // Browser checks read the live map in development builds only.
    if (import.meta.env.DEV) (window as unknown as { __gsMap?: maplibregl.Map }).__gsMap = instance
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right')
    instance.on('rotate', () => setBearing(instance.getBearing()))
    // A pinch that twists a few degrees shouldn't leave the estate skewed (B-23).
    instance.on('rotateend', () => { const b = instance.getBearing(); if (b !== 0 && Math.abs(b) < 12) instance.easeTo({ bearing: 0, duration: 200 }); declutterSoon() })
    instance.on('zoomend', () => { setZoom(Math.round(instance.getZoom() * 10) / 10); declutterSoon() })
    instance.on('style.load', () => { addLayers(instance); setReady(true); setMapObj(instance) })

    // Where to go when this base's pictures aren't coming: the map saved on this phone
    // when this isn't it; else, with signal, Esri's world imagery. Never one already
    // given up on.
    const nextBase = (base: BaseId): BaseId | null => {
      const noSignal = noSignalRef.current || !navigator.onLine
      return [savedRef.current?.base, noSignal ? null : 'world' as const]
        .find((b): b is BaseId => !!b && b !== base && !tried.current.has(b)) ?? null
    }
    // Pictures failed: where the view is against the map saved on this phone.
    const trouble = () => {
      const s = savedRef.current, b = instance.getBounds()
      const view = { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() }
      setTileErr(true)
      setTileWhere(!s ? null : s.base !== activeBaseRef.current ? 'other' : coverage(s, view, instance.getZoom()))
    }
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
      if (t.loaded[source]) trouble()
      instance.triggerRepaint()
    })
    instance.on('sourcedata', (e: maplibregl.MapSourceDataEvent) => {
      if (!e.tile || !e.sourceId) return
      const t = tiles.current
      t.loaded[e.sourceId] = (t.loaded[e.sourceId] ?? 0) + 1
      if (e.sourceId === CATASTRO) setCatastroErr(false)
      if (e.sourceId === baseSource(activeBaseRef.current)) { t.okSinceErr++; tried.current.clear() }
    })
    // Every tile asked for has answered or failed. Failed tiles report at once and good
    // ones only once decoded, so this is the first moment "none got through" is true.
    instance.on('idle', () => {
      const t = tiles.current, base = activeBaseRef.current, source = baseSource(base)
      if (t.errSinceIdle > 0) {
        const to = nextBase(base)
        if (to && !t.loaded[source] && (t.fails[source] ?? 0) >= FALLBACK_AFTER) {
          // A burst of failed pictures settles the map before the ones that did arrive
          // are decoded (a failed tile marks its source loaded in MapLibre), so decide
          // a moment later: some through is a gap, none is an outage.
          t.errSinceIdle = 0
          window.clearTimeout(fallbackTimer.current)
          fallbackTimer.current = window.setTimeout(() => {
            if (tiles.current !== t || activeBaseRef.current !== base) return
            // Asked again: the answer saying there is no signal may have come meanwhile.
            const to = nextBase(base)
            if (t.loaded[source] || !to) { trouble(); return }
            // The chosen picture isn't coming (the Spanish servers aren't answering, or
            // there is no signal): show one that does and say so.
            tried.current.add(base)
            setFallbackFrom(base); setFallbackTo(to); setFallbackNoted(false); setActiveBase(to); setTileErr(false)
            tiles.current = freshTiles()
          }, FALLBACK_GRACE_MS)
          return
        }
        trouble()
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
    return () => { resize.disconnect(); cancelAnimationFrame(labelFrame.current); window.clearTimeout(fallbackTimer.current); markers.current.forEach(m => m.marker.remove()); markers.current = []; instance.remove(); map.current = null; setMapObj(null); fitted.current = false }
    // The map is built once; later preference changes flip layers on the live style.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // A language chosen with the map open: MapLibre keeps the words it was built with,
  // so the ones already on the page are put right here, and the table it reads new
  // marks' names from is swapped.
  const language = useLang()
  useEffect(() => {
    const m = map.current
    if (!m) return
    const words = mapWords()
    m._locale = { ...m._locale, ...words }
    m.getCanvas().setAttribute('aria-label', words['Map.Title'])
    m.getContainer().querySelectorAll('.maplibregl-ctrl-attrib-button').forEach((b) => {
      b.setAttribute('title', words['AttributionControl.ToggleAttribution'])
      b.setAttribute('aria-label', words['AttributionControl.ToggleAttribution'])
    })
  }, [language, mapObj])

  // Base picture and property lines follow the choice without rebuilding the style.
  useEffect(() => { setActiveBase(prefs.base); setFallbackFrom(null); setTileErr(false); tiles.current = freshTiles(); tried.current.clear() }, [prefs.base])
  useEffect(() => { if (ready && map.current) showBase(map.current, activeBase) }, [ready, activeBase])
  useEffect(() => { if (ready && map.current) showCatastro(map.current, prefs.catastro); if (!prefs.catastro) setCatastroErr(false) }, [ready, prefs.catastro])

  /** Try again: ask for the picture's tiles again and nothing else. The style, the drawn layers and `ready` are left alone (B-01, I-11). */
  function retryTiles() {
    const instance = map.current
    if (!instance) return
    tiles.current = freshTiles()
    tried.current.clear()
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

  // Likely paths: asked for when the layer is on, drawn only on the normal map. What
  // the phone saved draws at once; the answer replaces it. Asked again after a failure
  // when the layer is turned on again.
  const pathsOn = prefs.layers.routes && view === 'cameras'
  const pathsAsked = useRef(false)
  useEffect(() => {
    if (!pathsOn || pathsAsked.current) return
    pathsAsked.current = true
    let answered = false
    setPathsErr('')
    savedCopy<{ paths: LikelyPath[] }>('/map/paths').then(got => { if (got && !answered && alive.current) setPaths(p => p ?? got.data.paths) })
    getFresh<{ paths: LikelyPath[] }>('/map/paths', { timeoutMs: LOAD_TIMEOUT_MS })
      .then(got => { answered = true; if (alive.current) setPaths(got.data.paths) })
      .catch((e: Failure) => {
        answered = true; pathsAsked.current = false
        if (alive.current) setPathsErr(noAnswer(e) ? t('mapPage.pathsNoSignal') : t('mapPage.pathsCouldnt', { why: e.message }))
      })
  }, [pathsOn])
  useEffect(() => { if (ready && map.current) renderPaths(map.current, pathsOn ? paths ?? [] : []) }, [ready, pathsOn, paths])
  // The estate's box, while the Map sheet (where it is set and saved) is open.
  useEffect(() => { if (ready && map.current) renderBox(map.current, settingsOpen ? estateBox : null) }, [ready, settingsOpen, estateBox])
  /** The ground the map shows above (or beside) the sheet, whatever way it is turned. */
  function viewBox(): Box | null {
    const instance = map.current, wrap = mapEl.current
    if (!instance || !wrap) return null
    const r = wrap.getBoundingClientRect(), sheet = wrap.parentElement?.querySelector('.bsheet')?.getBoundingClientRect()
    const beside = !!sheet?.height && sheet.width < r.width - 2
    const left = beside ? Math.min(r.width - 80, sheet!.right - r.left) : 0
    const bottom = sheet?.height && !beside ? Math.max(80, sheet.top - r.top) : r.height
    const corners = [[left, 0], [r.width, 0], [left, bottom], [r.width, bottom]].map(([x, y]) => instance.unproject([x, y]))
    const lats = corners.map(c => c.lat), lons = corners.map(c => c.lng)
    return { south: Math.min(...lats), north: Math.max(...lats), west: Math.min(...lons), east: Math.max(...lons) }
  }

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
      el.setAttribute('aria-label', pin.kind === 'stand' ? t('mapPage.standPin', { name: pin.name }) : t('pin.camera', { name: pin.name }))
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
  const draftWhat = editing?.kind === 'zone' && editing.points.length ? t('mapPage.thisOutline') : editing && !editing.id && editing.name.trim() ? t('mapPage.thisStand') : ''
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
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5000); return () => clearTimeout(timer) }, [notice])
  // A download that ends with the Map sheet closed says how it went on the map.
  useEffect(() => {
    if (!job.outcome || job.outcome === lastOutcome.current) return
    lastOutcome.current = job.outcome
    if (!settingsOpen) setNotice(job.outcome.text)
  }, [job.outcome]) // eslint-disable-line react-hooks/exhaustive-deps

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
      const outline = { type: 'Polygon', coordinates: [[...e.points, e.points[0]]] }
      // A new outline, or a redrawn one that keeps its place in the wind calls (B-22).
      if (e.kind === 'zone' && e.id) await api(`/zones/${e.id}`, send({ name: e.name.trim(), polygon: outline }, 'PATCH'))
      else if (e.kind === 'zone') await api('/zones', send({ name: e.name.trim(), kind: 'bedding', polygon: outline }, 'POST'))
      else if (e.kind === 'camera') await api(`/cameras/${e.id}/location`, send({ lat: point![1], lng: point![0] }, 'PUT'))
      else if (e.id) await api(`/stands/${e.id}`, send({ lat: point![1], lon: point![0] }, 'PATCH'))
      else created = await api<{ id: string }>('/stands', send({ name: e.name.trim(), lat: point![1], lon: point![0] }, 'POST'))
      // The draft stays until the new positions are in, so the pin never jumps back (B-17).
      // A reload that hangs doesn't hold the bar, though: the save itself is done.
      await Promise.race([load(), wait(RELOAD_WAIT_MS)])
      setEditing(null)
      if (created?.id) choose({ kind: 'stand', id: created.id }, 'peek')
      else if (e.id) setSnap('peek')
      setNotice(e.kind === 'zone' ? t('mapPage.beddingSaved') : t('common.saved'))
    } catch (x) {
      // Cancelled: the hunter has already left the drawing bar.
      if (ctl.signal.aborted) return
      const kept = e.kind === 'zone' ? t('mapPage.outlineKept') : t('mapPage.notSavedYet')
      setEditErr((x as Failure).timeout ? `${t('api.noAnswer')} ${kept}` : t('common.notSaved', { why: (x as Error).message }))
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
      if (kind === 'stand' && status === 409) throw Object.assign(new Error(t('mapPage.sitHistory')), { final: true })
      throw new Error(t('mapPage.didntRemove', { why: (x as Error).message }))
    }
    // Said once the map shows it, so the pin never lingers under 'Removed'.
    await load(); setSelected(null); setNotice(t('mapPage.removed'))
  }
  async function rename(id: string, name: string) {
    try { await api(`/stands/${id}`, { method: 'PATCH', body: JSON.stringify({ name }), timeoutMs: SAVE_TIMEOUT_MS }) }
    catch (x) { throw new Error(t('common.notSaved', { why: (x as Error).message })) }
    await load(); setNotice(t('mapPage.renamed'))
  }
  async function renameCamera(id: string, name: string) {
    try { await api(`/cameras/${id}/name`, { method: 'PATCH', body: JSON.stringify({ name }), timeoutMs: SAVE_TIMEOUT_MS }) }
    catch (x) { throw new Error(t('common.notSaved', { why: (x as Error).message })) }
    await load(); setNotice(t('mapPage.renamed'))
  }
  async function renameZone(id: string, name: string) {
    try { await api(`/zones/${id}`, { method: 'PATCH', body: JSON.stringify({ name }), timeoutMs: SAVE_TIMEOUT_MS }) }
    catch (x) { throw new Error(t('common.notSaved', { why: (x as Error).message })) }
    await load(); setNotice(t('mapPage.renamed'))
  }
  /** Back to the position the camera itself reports, and following it again (B-09). */
  async function useOwnGps(id: string) {
    try { await api(`/cameras/${id}/location`, { method: 'DELETE', timeoutMs: SAVE_TIMEOUT_MS }) }
    catch (x) { throw new Error(t('common.notSaved', { why: (x as Error).message })) }
    await load(); setNotice(t('mapPage.ownGps'))
  }
  /** The hill shape loads on the server in the background: start it, then ask how it
   *  went every few seconds. The map stays usable meanwhile (B-18). */
  async function loadTerrain() {
    setTerrainBusy(true); setTerrainErr('')
    try {
      let s = await api<TerrainStatus>('/terrain/refresh', { method: 'POST', timeoutMs: SAVE_TIMEOUT_MS })
      const until = Date.now() + TERRAIN_WAIT_MS
      while (s.state === 'loading' && Date.now() < until && alive.current) {
        await wait(TERRAIN_POLL_MS)
        s = await api<TerrainStatus>('/terrain/status', { timeoutMs: LOAD_TIMEOUT_MS })
      }
      if (!alive.current) return
      if (s.state === 'loaded') { await load(); setNotice(t('mapPage.terrainLoaded')) }
      else if (s.state === 'failed') setTerrainErr(t('mapPage.terrainCouldnt', { why: s.error ?? t('mapPage.tryLater') }))
      else setTerrainErr(t('mapPage.terrainStill'))
    } catch (x) {
      setTerrainErr(noAnswer(x) ? t('mapPage.terrainNoSignal') : t('mapPage.terrainCouldnt', { why: (x as Error).message }))
    } finally { if (alive.current) setTerrainBusy(false) }
  }

  const stand = selected?.kind === 'stand' ? data?.stands.find(s => s.id === selected.id) : null
  const camera = selected?.kind === 'camera' ? cameras.find(c => c.id === selected.id) : null
  const zone = selected?.kind === 'zone' ? data?.zones.find(z => z.id === selected.id) : null
  const air = data?.airflow
  const from = air?.source !== 'unknown' ? air?.wind_dir_deg : null
  const speed = air?.wind_speed_kmh
  // Nothing loaded is not the same as calm air: never state a verdict without the forecast.
  const windWord = !data ? (loading ? t('common.checking') : t('mapPage.windNotLoaded')) : from != null ? directionFrom(from) : speed == null ? t('sitWind.no_wind_data') : t('mapPage.tooLight')
  // Everything on the map is judged for the sit, 45 min after sunset, or now once dark.
  const cond = data?.conditions
  const windAt = !cond ? '' : cond.wind_now ? t('wind.now') : cond.wind_at_local ? t('mapPage.atTime', { time: cond.wind_at_local }) : ''
  const calm = windAt ? t('mapPage.calmAt', { when: windAt }) : t('mapPage.calm')
  const windLabel = air?.source === 'katabatic' ? t('mapPage.katabatic', { calm })
    : air?.source === 'anabatic' ? t('mapPage.anabatic', { calm })
      : t('mapPage.windWhen', { when: windAt || t('week.tonight') })
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
      if (checking) return one ? t('mapPage.stillCheckingLast') : t('mapPage.stillChecking')
      if (a.cameras.some(c => c.unreadable_nights)) return one ? t('mapPage.unreadableLast') : t('mapPage.unreadable')
      return one ? t('mapPage.noCameraLast') : t('mapPage.noCamera')
    }
    if (a.cameras.every(c => !c.visits)) {
      if (checking) return t('mapPage.noVisitsChecking', { count: checking })
      return one && a.so_far ? t('mapPage.noVisitsSoFar') : t('mapPage.noVisitsPeriod')
    }
    return ''
  })()
  const onSheetHeight = useCallback((px: number) => {
    const stage = stageRef.current
    if (!stage) return
    stage.style.setProperty('--sheet-h', `${px}px`)
    stage.dataset.sheet = px > stage.clientHeight * .7 ? 'tall' : px > 0 ? 'open' : ''
  }, [])
  const toWords = fallbackTo === savedEstate?.base ? t('mapPage.savedBase', { base: baseLabel(fallbackTo) }) : baseLabel(fallbackTo)
  const fromWords = fallbackFrom ? (fallbackFrom === 'world' ? baseLabel(fallbackFrom) : t('mapPage.fromIgn', { base: baseLabel(fallbackFrom) })) : ''
  const baseNote = fallbackFrom ? t('mapPage.baseNote', { from: fromWords, to: toWords, base: baseLabel(fallbackFrom) }) : null
  // With no signal only what was saved can show: say that, not that something failed.
  const noSignal = dataAge?.why === 'offline' || !navigator.onLine
  const tileNotice = tileErr ? savedEstate && noSignal ? savedWords(savedEstate, tileWhere)
    : t('mapPage.pictureGapSignal')
    : fallbackFrom && !fallbackNoted ? t('mapPage.fallback', { base: baseLabel(fallbackFrom), to: toWords }) : ''
  // A saved copy on screen: how old, and whether its wind is tonight's.
  // While the answer is on its way a saved copy says so only when it is old: one from a
  // minute ago is the map as it is.
  const waiting = dataAge && !dataAge.why
  const ageNotice = !dataAge || (waiting && (!loading || Date.now() - Date.parse(dataAge.at) < 10 * 60_000)) ? ''
    : `${waiting ? '' : `${noAnswerWords(dataAge.why)} `}${fromEarlierNight(dataAge.at)
      ? t('mapPage.fromEarlier', { when: whenLabel(dataAge.at) })
      : t('mapPage.from', { ago: ageLabel(dataAge.at) })}${waiting ? ` ${t('tonight.checkingNewer')}` : ''}`
  const editTitle = editing ? editing.kind === 'zone' ? editing.id ? t('mapPage.redraw', { name: editing.name }) : t('msheet.drawBedding') : editing.id ? t('mapPage.move', { name: editing.name }) : t('mapPage.newStand') : ''
  const busiest = paths?.[0]
  const pathsNote = !prefs.layers.routes ? null : pathsErr ? pathsErr : paths == null ? t('mapPage.pathsLoading')
    : !busiest ? t('mapPage.noPaths')
      : t('mapPage.paths', {
        count: paths!.length,
        route: busiest.cameras.join(t('mapPage.pathTo')),
        what: busiest.species[0]
          ? t('mapPage.pathSpecies', { label: busiest.species[0].label.toLocaleLowerCase(), n: busiest.species[0].nights })
          : t('mapPage.pathNights', { n: busiest.nights }),
      })

  if (fatal) return <div className="map-page map-page--fatal">
    <h1 className="page-title">{t('nav.map')}</h1>
    <div className="map-message map-message--error" role="alert">{fatal}</div>
    <div className="map-actions"><Link className="map-button" to="/stands">{t('nav.stands')}</Link><Link className="map-button" to="/cameras">{t('nav.cameras')}</Link></div>
  </div>

  return <div className="map-page" style={{ '--pin-scale': prefs.bigPins ? 1.25 : 1 } as CSSProperties}>
    <h1 className="sr-only">{t('nav.map')}</h1>
    {/* Tonight's wind says nothing about where the game was, and the views that show
        that turn the wind off: the map gets the room instead. */}
    {view === 'cameras' && <button type="button" className="map-windbar" aria-expanded={windOpen} aria-controls="map-wind-more" onClick={() => setWindOpen(v => !v)}>
      <span className="wind-direction" aria-hidden="true"><svg viewBox="0 0 40 40" style={{ transform: from == null ? undefined : `rotate(${downwind(from) - bearing}deg)` }}><circle cx="20" cy="20" r="18" />{from != null && <path d="M20 29V11m-6 6 6-6 6 6" />}</svg></span>
      <span className="map-wind-reading">
        <span>{windLabel}</span>
        <strong>{windWord}</strong>
        {from != null && <em>{scentTowards(downwind(from))}</em>}
      </span>
      <span className="map-wind-speed"><strong>{speed == null || !data ? '—' : Math.round(speed)}</strong><span>km/h</span></span>
      <span className="map-wind-chevron" aria-hidden="true">{windOpen ? '▴' : '▾'}</span>
    </button>}
    <div className="map-stage" ref={stageRef} data-editing={editing ? 'true' : undefined} data-labels={zoom >= LABEL_ZOOM ? 'on' : undefined}
      data-view={view === 'cameras' ? undefined : view}
      data-callouts={!prefs.layers.photos || view !== 'cameras' ? undefined : zoom >= CALLOUT_ZOOM ? 'on' : 'dots'}>
      <div className="map-canvas-wrap">
        <div ref={mapEl} className="map-canvas" aria-label={t('mapPage.canvas')} />
        {windOpen && view === 'cameras' && <div id="map-wind-more" className="map-wind-more">
          {!data && <p>{loading ? t('mapPage.gettingWind') : t('mapPage.windWithMap')}</p>}
          {air?.text && <p>{air.text}</p>}
          {cond && (cond.wind_now
            ? <p>{cond.sunset_local && cond.sunset && Date.parse(cond.sunset) <= Date.now() ? t('mapPage.judgedNowSunset', { time: cond.sunset_local }) : t('mapPage.judgedNow')}</p>
            : cond.wind_at_local && <p>{cond.sunset_local ? t('mapPage.judgedForSunset', { time: cond.wind_at_local, sunset: cond.sunset_local }) : t('mapPage.judgedFor', { time: cond.wind_at_local })}</p>)}
          {cond?.forecast_stale && cond.forecast_fetched_at && <p>{t('mapPage.oldForecast', { time: fmtTime(cond.forecast_fetched_at, { timeZone: 'Europe/Madrid' }) })}</p>}
          <p>{t('mapPage.arrows')}</p>
          <p className="map-caveat">{t('mapPage.indication')}</p>
        </div>}
        <ScalePill map={mapObj} />
        <div className="map-notices">
          {err && <div className="map-pill map-pill--error" role="alert"><span>{err}</span><button type="button" onClick={load} disabled={loading}>{t('common.tryAgain')}</button></div>}
          {ageNotice && <div className="map-pill map-pill--age" role="status"><span>{ageNotice}</span>{!waiting && <button type="button" onClick={load} disabled={loading}>{loading ? t('mapPage.trying') : t('common.tryAgain')}</button>}</div>}
          {tileNotice && <div className="map-pill" role="status"><span>{tileNotice}</span><button type="button" onClick={retryTiles}>{t('common.tryAgain')}</button>
            {!tileErr && <button type="button" aria-label={t('mapPage.keepThisMap')} onClick={() => setFallbackNoted(true)}>{t('common.ok')}</button>}</div>}
          {emptyEstate && <div className="map-pill map-pill--empty" role="status">
            <span>{data.stands.length + cameras.length === 0
              ? admin ? t('mapPage.emptyAdmin') : t('mapPage.empty')
              : admin ? t('mapPage.unplacedAdmin') : t('mapPage.unplaced')}</span>
            {admin && <span className="map-pill-actions">
              {data.stands.length + cameras.length === 0
                ? <><button type="button" onClick={() => startEdit({ kind: 'stand', name: '' })}>{t('msheet.addStand')}</button><Link to="/settings">{t('nav.settings')}</Link></>
                : <button type="button" onClick={() => { choose(null); setSettingsOpen(true); setSnap('full') }}>{t('mapPage.placeThem')}</button>}
            </span>}
          </div>}
          {measure.on && <div className="map-pill map-pill--measure" role="status">
            <span>{measure.result ?? (measure.points.length ? t('mapPage.secondPoint') : t('mapPage.twoPoints'))}</span>
            {measure.result && <button type="button" onClick={measure.clear}>{t('animals.clear')}</button>}
            <button type="button" onClick={measure.stop}>{t('common.done')}</button>
          </div>}
          {job.progress && sheet !== 'settings' && <div className="map-pill map-pill--saving" role="status">
            <span>{progressWords(job.progress)}</span><button type="button" aria-label={t('mapPage.stopSaving')} onClick={stopDownload}>{t('offline.stop')}</button>
          </div>}
          {notice && <div className="map-pill" role="status"><span>{notice}</span><button type="button" onClick={() => setNotice('')}>{t('common.ok')}</button></div>}
          {view === 'activity' && act.err && <div className="map-pill map-pill--error" role="alert"><span>{act.err}</span><button type="button" onClick={act.reload} disabled={act.loading}>{t('common.tryAgain')}</button></div>}
          {view === 'activity' && act.loading && <div className="map-pill" role="status"><span>{act.data ? t('mapPage.updating') : t('mapPage.loadingActivity')}</span></div>}
          {activityEmpty && <div className="map-pill map-pill--empty" role="status"><span>{activityEmpty}</span></div>}
          {view === 'replay' && replay.data && !replay.visits.length && <div className="map-pill map-pill--empty" role="status"><span>{t('mapPage.nothingCame')}</span></div>}
        </div>
        {!ready && <div className="map-loading" role="status">{t('mapPage.loadingMap')}</div>}
        {modeBar && view === 'activity' && act.picked && act.data && <ActivityCard camera={act.picked} data={act.data}
          onOpen={() => openCameraSheet(act.picked!.camera_id)} onClose={() => act.pick(null)} onHeight={onSheetHeight} />}

        {!editing && <div className="map-fabs map-fabs--right">
          <MapFab label={t('mapPage.fabSettings')} pressed={settingsOpen} onClick={() => { setSelected(null); setPick(null); setSettingsOpen(v => !v); setSnap('half') }}><StackIcon size={22} /></MapFab>
          <MapFab label={t('mapPage.fabNorth')} onClick={() => map.current?.easeTo({ bearing: 0, pitch: 0, duration: 300 })}>
            <svg className="map-north" viewBox="0 0 24 24" aria-hidden="true" style={{ transform: `rotate(${-bearing}deg)` }}>
              <path className="map-north-n" d="M12 3.5 15 12H9z" /><path className="map-north-s" d="M12 20.5 9 12h6z" /><path className="map-north-tick" d="M12 1v3" />
            </svg>
          </MapFab>
          <MapFab label={t('mapPage.fabFit')} disabled={!data || !ready} onClick={() => { if (map.current && data) fitEstate(map.current, data, cameras, 300, fitPadding()) }}><FrameCornersIcon size={22} /></MapFab>
          {/* Zoom with a glove on: pinching through a glove, or with one hand on a
              rifle, doesn't work. */}
          <MapFab label={t('lb.zoomIn')} disabled={!ready} onClick={() => map.current?.zoomIn({ duration: 250 })}><PlusIcon size={22} weight="bold" /></MapFab>
          <MapFab label={t('mapPage.zoomOut')} disabled={!ready} onClick={() => map.current?.zoomOut({ duration: 250 })}><MinusIcon size={22} weight="bold" /></MapFab>
        </div>}
        {!editing && <div className="map-fabs map-fabs--left">
          {me.message && <div className="map-pill map-pill--side" role="status"><span>{me.message}</span><button type="button" aria-label={t('mapPage.dismiss')} onClick={me.clearMessage}>{t('common.ok')}</button></div>}
          <MapFab label={measure.on ? t('msheet.stopMeasure') : t('mapPage.measureDistance')} pressed={measure.on} onClick={() => { measure.toggle(); closeSheet() }}><RulerIcon size={22} /></MapFab>
          <MapFab label={me.on ? t('msheet.hideMe') : t('msheet.showMe')} pressed={me.on} onClick={me.toggle}><NavigationArrowIcon size={22} /></MapFab>
        </div>}
        {editing && <Crosshair editing={editing} center={center} />}

        {sheet && <BottomSheet
          label={sheet === 'settings' ? t('mapPage.settingsSheet') : sheet === 'pick' ? t('map.whichOne') : stand ? t('mapPage.standPin', { name: stand.name }) : camera ? t('pin.camera', { name: camera.name }) : t('mapPage.beddingSheet', { name: zone?.name ?? '' })}
          snap={snap} onSnap={setSnap} onClose={closeSheet} onHeight={onSheetHeight}
          returnFocus={() => selected ? mapEl.current?.querySelector(`.map-pin[data-kind="${selected.kind}"][data-id="${selected.id}"]`) : null}
          focusKey={sheet === 'settings' ? 'settings' : `${sheet}-${selKey}`}
          header={sheet === 'settings' ? <><span className="map-eyebrow">{t('nav.map')}</span><h2 className="bsheet-name">{t('mapPage.howLooks')}</h2></>
            : sheet === 'pick' ? <PickHeader count={pick!.length} />
              : stand ? <StandHeader stand={stand} /> : camera ? <CameraHeader camera={camera} /> : zone ? <ZoneHeader zone={zone} /> : null}>
          {sheet === 'settings' && <MapSheet view={view} onView={setView} prefs={prefs} onPrefs={setPrefs} onRetryBase={() => { if (fallbackFrom || tileErr) retryTiles() }} zoom={zoom} baseNote={baseNote}
            catastroNote={catastroErr ? t('mapPage.catastroErr') : null}
            admin={admin} measuring={measure.on} meOn={me.on}
            onMeasure={() => { measure.toggle(); closeSheet() }} onMe={() => { me.toggle(); closeSheet() }}
            onAddStand={() => startEdit({ kind: 'stand', name: '' })}
            onDrawBedding={() => { setSelected(null); startEdit({ kind: 'zone', name: t('mapPage.beddingN', { n: (data?.zones.length ?? 0) + 1 }) }) }}
            onPlace={u => { setSelected({ kind: u.kind, id: u.id }); startEdit({ kind: u.kind, id: u.id, name: u.name }) }}
            unplaced={unplaced}
            terrain={{ needed: !!data && !data.terrain_loaded, outside: data?.terrain_outside ?? [], busy: terrainBusy, err: terrainErr, onLoad: loadTerrain }}
            paths={pathsNote}
            offline={{ cameras, viewBox, onBox: setEstateBox }} />}
          {sheet === 'pick' && <PickBody pins={pick!} onPick={select} />}
          {stand && <StandBody stand={stand} scentRange={data!.scent_range_m} admin={admin}
            onMove={() => startEdit({ kind: 'stand', id: stand.id, name: stand.name, at: [stand.lon, stand.lat] })}
            onRemove={() => remove('stand', stand.id)} onRename={name => rename(stand.id, name)} />}
          {camera && <CameraBody camera={camera} admin={admin} onRename={name => renameCamera(camera.id, name)} onUseOwnGps={() => useOwnGps(camera.id)}
            onAlerts={(alerts, enabled) => setCameras(cs => cs.map(c => c.id === camera.id ? { ...c, alerts, alerts_enabled: enabled } : c))}
            onMove={() => startEdit({ kind: 'camera', id: camera.id, name: camera.name, at: [camera.lon, camera.lat] })} />}
          {zone && <ZoneBody zone={zone} admin={admin} onRemove={() => remove('zone', zone.id)} onRename={name => renameZone(zone.id, name)}
            onRedraw={() => { const ring = zone.polygon.coordinates[0]; startEdit({ kind: 'zone', id: zone.id, name: zone.name, at: ring.length ? [ring.reduce((a, p) => a + p[0], 0) / ring.length, ring.reduce((a, p) => a + p[1], 0) / ring.length] : undefined }) }} />}
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
