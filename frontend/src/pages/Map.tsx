import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

type Camera = {
  id: string
  name: string
  lat: number | null
  lng: number | null
  sightings: number
  battery_pct: number | null
}
type Estate = { name: string; lat: number; lng: number }
type Zone = {
  id: string
  kind: string
  name: string
  polygon: { type: string; coordinates: number[][][] }
  centroid: { lat: number; lon: number } | null
}
type WindReport = {
  status: string
  text: string
  scent_bearing?: number
  speed_kmh?: number
  range_m?: number
  half_deg?: number
  source?: string
  hit_zones?: { zone: string; distance_m: number }[]
}
type StandOut = {
  id: string
  name: string
  lat: number | null
  lon: number | null
  wind: WindReport
  approaches: { zone: string; approach_deg: number; distance_m: number }[]
}
type SafeGround = {
  status: string
  cells: { lat: number; lon: number; safe: boolean; nearest_m: number }[]
  note?: string
  scent_bearing?: number
}
type Route = {
  zone: string
  camera: string
  from: { lat: number; lon: number }
  to: { lat: number; lon: number }
  detections: number
  avg_hour: number | null
}
type Airflow = {
  source: 'synoptic' | 'katabatic' | 'anabatic' | 'unknown'
  wind_dir_deg: number | null
  wind_speed_kmh: number | null
  confidence?: string | null
  slope?: { downhill_deg: number | null; slope_pct: number; elevation_m: number } | null
  text?: string | null
}
type MapTonight = {
  conditions: { wind_dir_deg: number | null; wind_speed_kmh: number | null }
  airflow: Airflow
  zones: Zone[]
  stands: StandOut[]
  safe_ground: SafeGround
  routes: Route[]
  scent_range_m: number
  terrain_loaded: boolean
}

const STYLE = {
  version: 8,
  sources: {
    sat: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: 'Imagery © Esri',
    },
  },
  layers: [{ id: 'sat', type: 'raster', source: 'sat' }],
} as unknown as maplibregl.StyleSpecification

const compass = (d: number) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(d / 45) % 8]
const windColor = (s: string) =>
  s === 'clean' ? '#3FB950' : s === 'scent_carries' ? '#E5534B' : '#E3A008'

const empty = { type: 'FeatureCollection', features: [] } as GeoJSON.FeatureCollection

/** Metres offset -> lat/lon, good enough for drawing a cone a few hundred metres long. */
function offset(lat: number, lon: number, bearingDeg: number, m: number): [number, number] {
  const br = (bearingDeg * Math.PI) / 180
  const dLat = (m * Math.cos(br)) / 111_320
  const dLon = (m * Math.sin(br)) / (111_320 * Math.cos((lat * Math.PI) / 180))
  return [lon + dLon, lat + dLat]
}

export default function MapPage() {
  const mapEl = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const drawingRef = useRef(false)
  const draftRef = useRef<[number, number][]>([])
  const placingRef = useRef<string | null>(null)

  const [cameras, setCameras] = useState<Camera[]>([])
  const [data, setData] = useState<MapTonight | null>(null)
  const [drawing, setDrawing] = useState(false)
  const [draftLen, setDraftLen] = useState(0)
  const [placing, setPlacing] = useState<string | null>(null)
  const [show, setShow] = useState({ bedding: true, safe: true, routes: false, cones: true })
  const [busy, setBusy] = useState('')

  // ── sources / layers ────────────────────────────────────────
  function setSrc(id: string, fc: GeoJSON.FeatureCollection) {
    const s = mapRef.current?.getSource(id) as maplibregl.GeoJSONSource | undefined
    s?.setData(fc)
  }

  function renderAll(d: MapTonight, cams: Camera[]) {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return

    // bedding polygons
    setSrc('zones', {
      type: 'FeatureCollection',
      features: d.zones.map((z) => ({
        type: 'Feature',
        properties: { id: z.id, name: z.name, kind: z.kind },
        geometry: z.polygon as GeoJSON.Polygon,
      })),
    })

    // safe / unsafe ground for tonight
    setSrc('safe', {
      type: 'FeatureCollection',
      features: (show.safe ? d.safe_ground.cells : []).map((c) => ({
        type: 'Feature',
        properties: { safe: c.safe ? 1 : 0 },
        geometry: { type: 'Point', coordinates: [c.lon, c.lat] },
      })),
    })

    // Scent cones. Drawn as nested wedges rather than one flat wash: the overlap
    // concentrates near the stand and thins out with distance, which is what a plume
    // actually does — and makes the thing impossible to miss at a glance.
    const BANDS = 5
    const cones: GeoJSON.Feature[] = []
    const spines: GeoJSON.Feature[] = []
    const heads: GeoJSON.Feature[] = []
    if (show.cones) {
      for (const s of d.stands) {
        const sb = s.wind.scent_bearing
        if (s.lat == null || s.lon == null || sb == null) continue
        const r = s.wind.range_m ?? d.scent_range_m
        const half = s.wind.half_deg ?? 22.5
        const step = Math.max(2, half / 6)
        for (let b = 1; b <= BANDS; b++) {
          const rr = (r * b) / BANDS
          const ring: [number, number][] = [[s.lon, s.lat]]
          for (let a = -half; a <= half; a += step) ring.push(offset(s.lat, s.lon, sb + a, rr))
          ring.push(offset(s.lat, s.lon, sb + half, rr))
          ring.push([s.lon, s.lat])
          cones.push({
            type: 'Feature',
            properties: { status: s.wind.status, band: b },
            geometry: { type: 'Polygon', coordinates: [ring] },
          })
        }
        // Centreline: the thing that gets animated, so the map shows air *moving*.
        spines.push({
          type: 'Feature',
          properties: { status: s.wind.status },
          geometry: {
            type: 'LineString',
            coordinates: [[s.lon, s.lat], offset(s.lat, s.lon, sb, r)],
          },
        })
        heads.push({
          type: 'Feature',
          properties: { status: s.wind.status, rot: sb, label: `${Math.round(s.wind.speed_kmh ?? 0)} km/h` },
          geometry: { type: 'Point', coordinates: offset(s.lat, s.lon, sb, r * 0.82) },
        })
      }
    }
    setSrc('cones', { type: 'FeatureCollection', features: cones })
    setSrc('spines', { type: 'FeatureCollection', features: spines })
    setSrc('heads', { type: 'FeatureCollection', features: heads })

    // inferred bedding -> camera links
    setSrc('routes', {
      type: 'FeatureCollection',
      features: (show.routes ? d.routes : []).map((r) => ({
        type: 'Feature',
        properties: { label: `${r.zone} → ${r.camera} (${r.detections})` },
        geometry: { type: 'LineString', coordinates: [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]] },
      })),
    })

    // markers: cameras (draggable) + stands (wind-coloured)
    markers.current.forEach((m) => m.remove())
    markers.current = []
    cams.filter((c) => c.lat != null && c.lng != null).forEach((c) => {
      const el = document.createElement('div')
      el.style.cssText =
        'width:16px;height:16px;border-radius:50%;background:#3FB9B0;border:2px solid #fff;' +
        'box-shadow:0 0 8px rgba(63,185,176,.8);cursor:pointer'
      const mk = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([c.lng as number, c.lat as number])
        .setPopup(new maplibregl.Popup({ offset: 16 }).setHTML(
          `<div style="color:#111"><b>${c.name}</b><br>camera · ${c.sightings} sightings</div>`))
        .addTo(mapRef.current as maplibregl.Map)
      mk.on('dragend', () => {
        const ll = mk.getLngLat()
        api(`/cameras/${c.id}/location`, { method: 'PUT', body: JSON.stringify({ lat: ll.lat, lng: ll.lng }) })
          .then(load).catch(() => {})
      })
      markers.current.push(mk)
    })
    d.stands.filter((s) => s.lat != null && s.lon != null).forEach((s) => {
      const col = windColor(s.wind.status)
      const el = document.createElement('div')
      el.style.cssText =
        `width:26px;height:26px;border-radius:6px;background:${col};border:2px solid #fff;` +
        'cursor:pointer;display:flex;align-items:center;justify-content:center;' +
        'color:#06210C;font-size:13px;font-weight:700'
      el.textContent = '🪑'
      const app = s.approaches.length
        ? `<br><span style="opacity:.7">approach ${s.approaches.map((a) => compass(a.approach_deg)).join(', ')}</span>`
        : ''
      const mk = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([s.lon as number, s.lat as number])
        .setPopup(new maplibregl.Popup({ offset: 18 }).setHTML(
          `<div style="color:#111;max-width:230px"><b>${s.name}</b><br>${s.wind.text}${app}</div>`))
        .addTo(mapRef.current as maplibregl.Map)
      mk.on('dragend', () => {
        const ll = mk.getLngLat()
        api(`/stands/${s.id}`, { method: 'PATCH', body: JSON.stringify({ lat: ll.lat, lon: ll.lng }) })
          .then(load).catch(() => {})
      })
      markers.current.push(mk)
    })
  }

  async function load() {
    const [cams, d] = await Promise.all([api<Camera[]>('/cameras'), api<MapTonight>('/map/tonight')])
    setCameras(cams)
    setData(d)
    renderAll(d, cams)
    const map = mapRef.current
    if (map) {
      const pts: [number, number][] = [
        ...cams.filter((c) => c.lat != null).map((c) => [c.lng as number, c.lat as number] as [number, number]),
        ...d.zones.flatMap((z) => (z.polygon.coordinates[0] || []).map((p) => [p[0], p[1]] as [number, number])),
      ]
      if (pts.length > 1 && !drawingRef.current) {
        const b = new maplibregl.LngLatBounds()
        pts.forEach((p) => b.extend(p))
        map.fitBounds(b, { padding: 70, maxZoom: 16, duration: 0 })
      }
    }
  }

  useEffect(() => {
    if (data) renderAll(data, cameras)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])

  // Drift the dash pattern along the centreline so the cone reads as air on the
  // move. MapLibre has no dash-offset to animate, so cycle the pattern instead —
  // and pace it by wind speed, so a gale visibly runs and a drainage flow creeps.
  useEffect(() => {
    if (!show.cones) return
    const DASHES: [number, number, number][] = [
      [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5],
      [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0],
    ]
    const speed = data?.airflow?.wind_speed_kmh ?? 6
    const period = Math.max(45, 220 - speed * 7)   // faster wind, faster drift
    let i = 0
    const t = window.setInterval(() => {
      const map = mapRef.current
      if (!map || !map.getLayer('spines-line')) return
      map.setPaintProperty('spines-line', 'line-dasharray', DASHES[i % DASHES.length])
      i++
    }, period)
    return () => window.clearInterval(t)
  }, [show.cones, data?.airflow?.wind_speed_kmh])

  // ── drawing ─────────────────────────────────────────────────
  function updateDraft() {
    const pts = draftRef.current
    setDraftLen(pts.length)
    const features: GeoJSON.Feature[] = pts.map((p) => ({
      type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: p },
    }))
    if (pts.length >= 2) {
      features.push({
        type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates: pts.length >= 3 ? [...pts, pts[0]] : pts },
      })
    }
    setSrc('draft', { type: 'FeatureCollection', features })
  }

  function startDraw() {
    draftRef.current = []
    drawingRef.current = true
    setDrawing(true)
    updateDraft()
  }

  function cancelDraw() {
    draftRef.current = []
    drawingRef.current = false
    setDrawing(false)
    updateDraft()
  }

  async function finishDraw() {
    const pts = draftRef.current
    if (pts.length < 3) return
    const name = window.prompt('Name this bedding area', `Bedding ${(data?.zones.length ?? 0) + 1}`)
    if (!name) return
    setBusy('Saving…')
    try {
      await api('/zones', {
        method: 'POST',
        body: JSON.stringify({
          name, kind: 'bedding',
          polygon: { type: 'Polygon', coordinates: [[...pts, pts[0]]] },
        }),
      })
      cancelDraw()
      await load()
    } catch (e) {
      window.alert((e as Error).message)
    }
    setBusy('')
  }

  useEffect(() => {
    if (!mapEl.current || mapRef.current) return
    const map = new maplibregl.Map({ container: mapEl.current, style: STYLE, center: [-1.3608, 39.0947], zoom: 14 })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    map.on('load', () => {
      map.resize()
      for (const id of ['safe', 'zones', 'cones', 'spines', 'heads', 'routes', 'draft']) {
        map.addSource(id, { type: 'geojson', data: empty })
      }
      // Safe ground sits under everything: it is context, not an instruction.
      map.addLayer({
        id: 'safe-fill', type: 'circle', source: 'safe',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 6, 16, 22],
          'circle-color': ['case', ['==', ['get', 'safe'], 1], '#3FB950', '#E5534B'],
          'circle-opacity': 0.22, 'circle-blur': 1,
        },
      })
      // Nested bands stack up near the stand and thin out downwind.
      map.addLayer({
        id: 'cones-fill', type: 'fill', source: 'cones',
        paint: {
          'fill-color': ['case', ['==', ['get', 'status'], 'clean'], '#3FB950', '#E5534B'],
          'fill-opacity': 0.11,
        },
      })
      map.addLayer({
        id: 'cones-edge', type: 'line', source: 'cones',
        filter: ['==', ['get', 'band'], 5],
        paint: {
          'line-color': ['case', ['==', ['get', 'status'], 'clean'], '#3FB950', '#E5534B'],
          'line-width': 1.5, 'line-opacity': 0.55,
        },
      })
      // Animated centreline — the dash pattern is cycled below so the air reads as
      // moving rather than as a static wedge.
      map.addLayer({
        id: 'spines-line', type: 'line', source: 'spines',
        paint: {
          'line-color': ['case', ['==', ['get', 'status'], 'clean'], '#8FE39A', '#FF8A80'],
          'line-width': 3,
          'line-opacity': 0.9,
          'line-dasharray': [0, 4, 3],
        },
      })
      map.addLayer({
        id: 'heads-sym', type: 'symbol', source: 'heads',
        layout: {
          'text-field': '➤',
          'text-size': 22,
          'text-rotate': ['get', 'rot'],
          'text-rotation-alignment': 'map',
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': ['case', ['==', ['get', 'status'], 'clean'], '#8FE39A', '#FF8A80'],
          'text-halo-color': '#000', 'text-halo-width': 1.2,
        },
      })
      map.addLayer({
        id: 'zones-fill', type: 'fill', source: 'zones',
        paint: { 'fill-color': '#D9B370', 'fill-opacity': 0.28 },
      })
      map.addLayer({
        id: 'zones-line', type: 'line', source: 'zones',
        paint: { 'line-color': '#D9B370', 'line-width': 2 },
      })
      map.addLayer({
        id: 'zones-label', type: 'symbol', source: 'zones',
        layout: { 'text-field': ['get', 'name'], 'text-size': 12 },
        paint: { 'text-color': '#fff', 'text-halo-color': '#000', 'text-halo-width': 1.5 },
      })
      map.addLayer({
        id: 'routes-line', type: 'line', source: 'routes',
        paint: { 'line-color': '#3FB9B0', 'line-width': 2, 'line-dasharray': [2, 2], 'line-opacity': 0.8 },
      })
      map.addLayer({
        id: 'draft-line', type: 'line', source: 'draft',
        paint: { 'line-color': '#D9B370', 'line-width': 2, 'line-dasharray': [1, 1] },
      })
      map.addLayer({
        id: 'draft-pts', type: 'circle', source: 'draft',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: { 'circle-radius': 5, 'circle-color': '#D9B370', 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 },
      })

      map.on('click', 'zones-fill', (e) => {
        if (drawingRef.current) return
        const f = e.features?.[0]
        if (!f) return
        const id = f.properties?.id as string
        const name = f.properties?.name as string
        if (window.confirm(`Delete bedding area "${name}"?`)) {
          api(`/zones/${id}`, { method: 'DELETE' }).then(load).catch(() => {})
        }
      })

      map.on('click', (e) => {
        if (drawingRef.current) {
          draftRef.current = [...draftRef.current, [e.lngLat.lng, e.lngLat.lat]]
          updateDraft()
          return
        }
        const camId = placingRef.current
        if (!camId) return
        api(`/cameras/${camId}/location`, {
          method: 'PUT', body: JSON.stringify({ lat: e.lngLat.lat, lng: e.lngLat.lng }),
        }).then(() => { placingRef.current = null; setPlacing(null); load() }).catch(() => {})
      })

      api<Estate>('/estate').then((est) => map.setCenter([est.lng, est.lat])).catch(() => {})
      load().catch(() => {})
    })

    return () => { map.remove(); mapRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const unplaced = cameras.filter((c) => c.lat == null || c.lng == null)
  const cond = data?.conditions
  const sg = data?.safe_ground
  const air = data?.airflow

  return (
    <div style={{ position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Map</div>
        {air && air.source === 'synoptic' && cond?.wind_dir_deg != null && (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
            Tonight: wind {compass(cond.wind_dir_deg)} {Math.round(cond.wind_speed_kmh ?? 0)} km/h
          </div>
        )}
        {air && (air.source === 'katabatic' || air.source === 'anabatic') && air.slope?.downhill_deg != null && (
          <div style={{ fontSize: 13, color: 'var(--sand)' }}>
            Calm — {air.source === 'katabatic' ? 'drainage' : 'upslope'}{' '}
            {compass(air.source === 'katabatic' ? air.slope.downhill_deg : (air.slope.downhill_deg + 180) % 360)}
            {' '}~{air.wind_speed_kmh} km/h
          </div>
        )}
        {air && air.source === 'unknown' && (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Tonight: too calm to call</div>
        )}
        {data && !data.terrain_loaded && (
          <button
            onClick={async () => {
              setBusy('Loading terrain…')
              try {
                const r = await api<{ relief_m: number }>('/terrain/refresh', { method: 'POST' })
                window.alert(`Terrain loaded — ${r.relief_m} m of relief. Drainage advice is on.`)
                await load()
              } catch (e) { window.alert((e as Error).message) }
              setBusy('')
            }}
            style={{
              background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--sand)',
              borderRadius: 8, padding: '5px 10px', cursor: 'pointer', fontSize: 12,
            }}
          >Load terrain</button>
        )}
        <button
          onClick={drawing ? finishDraw : startDraw}
          className="btn"
          style={{ width: 'auto', marginLeft: 'auto', padding: '7px 13px', fontSize: 13 }}
          disabled={!!busy || (drawing && draftLen < 3)}
        >
          {busy || (drawing ? `Finish area (${draftLen})` : 'Draw bedding')}
        </button>
        {drawing && (
          <button onClick={cancelDraw} style={{
            background: 'var(--surface-2)', border: '1px solid var(--border)', color: 'var(--text-dim)',
            borderRadius: 8, padding: '7px 12px', cursor: 'pointer', fontSize: 13,
          }}>Cancel</button>
        )}
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 8, fontSize: 12 }}>
        {([
          ['bedding', 'Bedding'], ['safe', 'Safe ground'], ['cones', 'Scent cones'], ['routes', 'Routes'],
        ] as const).map(([k, label]) => (
          <label key={k} style={{ display: 'flex', alignItems: 'center', gap: 5, color: 'var(--text-dim)', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={show[k]}
              onChange={(e) => {
                setShow((p) => ({ ...p, [k]: e.target.checked }))
                const map = mapRef.current
                if (k === 'bedding' && map) {
                  const v = e.target.checked ? 'visible' : 'none'
                  for (const l of ['zones-fill', 'zones-line', 'zones-label']) map.setLayoutProperty(l, 'visibility', v)
                }
              }}
            />
            {label}
          </label>
        ))}
      </div>

      <div ref={mapEl} style={{
        height: 'calc(100vh - 260px)', minHeight: 380, borderRadius: 12,
        overflow: 'hidden', border: '1px solid var(--border)',
      }} />

      {drawing && (
        <div style={{
          position: 'absolute', top: 92, left: 12, right: 12, background: 'rgba(22,29,26,.94)',
          border: '1px solid var(--border)', borderRadius: 10, padding: '9px 12px', zIndex: 6, fontSize: 12,
        }}>
          Tap the map to trace where they lie up — three points minimum, then <b>Finish area</b>.
        </div>
      )}

      {!drawing && data && (
        <div style={{
          position: 'absolute', bottom: 12, left: 12, background: 'rgba(22,29,26,.92)',
          border: '1px solid var(--border)', borderRadius: 10, padding: '9px 12px',
          maxWidth: 300, zIndex: 6, fontSize: 11, lineHeight: 1.5,
        }}>
          <div style={{ display: 'flex', gap: 12, marginBottom: 5, flexWrap: 'wrap' }}>
            <span><span style={{ color: '#3FB950' }}>■</span> scent clear</span>
            <span><span style={{ color: '#E5534B' }}>■</span> scent on bedding</span>
            <span><span style={{ color: '#D9B370' }}>■</span> bedding</span>
          </div>
          <div style={{ color: 'var(--text-dim)' }}>
            {data.zones.length === 0
              ? 'No bedding drawn yet — draw an area and the wind advice turns on.'
              : sg?.note || 'Wind too light to map tonight.'}
          </div>
          {air?.text && air.source !== 'synoptic' && (
            <div style={{ color: 'var(--sand)', marginTop: 5 }}>{air.text}</div>
          )}
        </div>
      )}

      {unplaced.length > 0 && !drawing && (
        <div style={{
          position: 'absolute', top: 92, left: 12, background: 'var(--surface)',
          border: '1px solid var(--border)', borderRadius: 10, padding: 12, maxWidth: 230, zIndex: 5,
        }}>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
            {placing ? 'Tap the map to drop it' : 'Place your cameras:'}
          </div>
          {unplaced.map((c) => (
            <button key={c.id} onClick={() => { placingRef.current = c.id; setPlacing(c.id) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left', marginBottom: 6,
                background: placing === c.id ? 'var(--go)' : 'var(--surface-2)',
                color: placing === c.id ? '#06210C' : 'var(--text)',
                border: '1px solid var(--border)', borderRadius: 8, padding: '6px 10px',
                cursor: 'pointer', fontSize: 13,
              }}>
              {placing === c.id ? `Placing ${c.name}…` : `Place ${c.name}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
