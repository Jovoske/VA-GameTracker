import maplibregl, { type Map } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { measureLabel, type LngLat } from './geometry'
import { setSource } from './layers'

/**
 * Measure: tap two points, get "134 m · north-east" on the line between them. A
 * third tap starts a new line from there. The label is a DOM marker because the map
 * style carries no fonts, which keeps it working with no network.
 */
export function useMeasure(map: Map | null, ready: boolean) {
  const [on, setOn] = useState(false)
  const [points, setPoints] = useState<LngLat[]>([])
  const label = useRef<maplibregl.Marker | null>(null)

  useEffect(() => {
    if (!map || !ready) return
    const features: GeoJSON.Feature[] = points.map(coordinates => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates } }))
    if (points.length === 2) features.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: points } })
    setSource(map, 'measure', features)
    label.current?.remove(); label.current = null
    if (points.length === 2) {
      const el = document.createElement('div')
      el.className = 'measure-tag'
      el.textContent = measureLabel(points[0], points[1])
      const mid: LngLat = [(points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2]
      label.current = new maplibregl.Marker({ element: el, anchor: 'bottom', offset: [0, -8] }).setLngLat(mid).addTo(map)
    }
  }, [map, ready, points])
  useEffect(() => () => { label.current?.remove(); label.current = null }, [])

  return {
    on,
    points,
    result: points.length === 2 ? measureLabel(points[0], points[1]) : null,
    add: (p: LngLat) => setPoints(prev => prev.length >= 2 ? [p] : [...prev, p]),
    toggle: () => { setPoints([]); setOn(v => !v) },
    stop: () => { setPoints([]); setOn(false) },
    clear: () => setPoints([]),
  }
}
