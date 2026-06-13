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
  signal_pct: number | null
}
type Estate = { name: string; lat: number; lng: number }

// Satellite base map, no API token required (Esri World Imagery).
const STYLE = {
  version: 8,
  sources: {
    sat: {
      type: 'raster',
      tiles: [
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      ],
      tileSize: 256,
      attribution: 'Imagery © Esri',
    },
  },
  layers: [{ id: 'sat', type: 'raster', source: 'sat' }],
} as unknown as maplibregl.StyleSpecification

export default function MapPage() {
  const mapEl = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const markers = useRef<Record<string, maplibregl.Marker>>({})
  const placingRef = useRef<string | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [placing, setPlacing] = useState<string | null>(null)

  function renderMarkers(cams: Camera[]) {
    const map = mapRef.current
    if (!map) return
    Object.values(markers.current).forEach((m) => m.remove())
    markers.current = {}
    const placed = cams.filter((c) => c.lat != null && c.lng != null)
    placed.forEach((c) => {
      const el = document.createElement('div')
      const size = Math.min(44, 18 + Math.sqrt(c.sightings) * 2)
      el.style.cssText =
        `width:${size}px;height:${size}px;border-radius:50%;background:#3FB950;` +
        `border:2px solid #fff;box-shadow:0 0 12px rgba(63,185,80,.85);cursor:pointer;` +
        `display:flex;align-items:center;justify-content:center;color:#06210C;font-size:10px;font-weight:700`
      el.textContent = String(c.sightings)
      const marker = new maplibregl.Marker({ element: el, draggable: true })
        .setLngLat([c.lng as number, c.lat as number])
        .setPopup(
          new maplibregl.Popup({ offset: 22 }).setHTML(
            `<div style="color:#111"><b>${c.name}</b><br>${c.sightings} sightings<br>battery ${c.battery_pct ?? '–'}%</div>`,
          ),
        )
        .addTo(map)
      marker.on('dragend', () => {
        const ll = marker.getLngLat()
        api(`/cameras/${c.id}/location`, {
          method: 'PUT',
          body: JSON.stringify({ lat: ll.lat, lng: ll.lng }),
        }).catch(() => {})
      })
      markers.current[c.id] = marker
    })
    if (placed.length > 1) {
      const b = new maplibregl.LngLatBounds()
      placed.forEach((c) => b.extend([c.lng as number, c.lat as number]))
      map.fitBounds(b, { padding: 80, maxZoom: 16 })
    }
  }

  async function load() {
    const cams = await api<Camera[]>('/cameras')
    setCameras(cams)
    renderMarkers(cams)
  }

  useEffect(() => {
    if (!mapEl.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: mapEl.current,
      style: STYLE,
      center: [-1.3608, 39.0947],
      zoom: 14,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map

    map.on('click', (e) => {
      const camId = placingRef.current
      if (!camId) return
      api(`/cameras/${camId}/location`, {
        method: 'PUT',
        body: JSON.stringify({ lat: e.lngLat.lat, lng: e.lngLat.lng }),
      })
        .then(() => {
          placingRef.current = null
          setPlacing(null)
          load()
        })
        .catch(() => {})
    })

    map.on('load', () => {
      map.resize()
      api<Estate>('/estate').then((est) => map.setCenter([est.lng, est.lat])).catch(() => {})
      load()
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  const unplaced = cameras.filter((c) => c.lat == null || c.lng == null)

  return (
    <div style={{ position: 'relative' }}>
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 12 }}>Map</div>
      <div
        ref={mapEl}
        style={{
          height: 'calc(100vh - 180px)',
          minHeight: 420,
          borderRadius: 12,
          overflow: 'hidden',
          border: '1px solid var(--border)',
        }}
      />
      {unplaced.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: 52,
            left: 12,
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            padding: 12,
            maxWidth: 240,
            zIndex: 5,
          }}
        >
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 8 }}>
            {placing ? 'Click the map to drop it (drag to fine-tune)' : 'Place your cameras:'}
          </div>
          {unplaced.map((c) => (
            <button
              key={c.id}
              onClick={() => {
                placingRef.current = c.id
                setPlacing(c.id)
              }}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                marginBottom: 6,
                background: placing === c.id ? 'var(--go)' : 'var(--surface-2)',
                color: placing === c.id ? '#06210C' : 'var(--text)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: '6px 10px',
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              {placing === c.id ? `Placing ${c.name}…` : `Place ${c.name}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
