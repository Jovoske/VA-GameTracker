export type Camera = { id: string; name: string; lat: number | null; lng: number | null; sightings: number; battery_pct: number | null; signal_pct?: number | null; last_capture?: string | null }
export type Zone = { id: string; name: string; kind: string; polygon: GeoJSON.Polygon }
export type WindReport = { status: string; text: string; scent_bearing?: number; speed_kmh?: number; range_m?: number; half_deg?: number; source?: string }
export type MapStand = { id: string; name: string; lat: number | null; lon: number | null; wind: WindReport; approaches: { zone: string; approach_deg: number; distance_m: number }[] }
export type MapData = {
  conditions: { wind_dir_deg: number | null; wind_speed_kmh: number | null }
  airflow: { source: string; wind_dir_deg: number | null; wind_speed_kmh: number | null; text?: string; confidence?: string }
  zones: Zone[]; stands: MapStand[]
  safe_ground: { status: string; cells: { lat: number; lon: number; safe: boolean }[]; note?: string }
  routes: { zone: string; camera: string; from: { lat: number; lon: number }; to: { lat: number; lon: number }; detections: number }[]
  scent_range_m: number; terrain_loaded: boolean
}
export const compass = (degrees: number) => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(((degrees % 360) + 360) % 360 / 45) % 8]
// Compass words, not degrees. "From the north-west" reads at a glance.
const DIRECTION: Record<string, string> = { N: 'north', NE: 'north-east', E: 'east', SE: 'south-east', S: 'south', SW: 'south-west', W: 'west', NW: 'north-west' }
export const direction = (degrees: number) => DIRECTION[compass(degrees)]
export const downwind = (from: number) => (from + 180) % 360
export function offset(lat: number, lon: number, bearing: number, metres: number): [number, number] {
  const r = bearing * Math.PI / 180
  return [lon + metres * Math.sin(r) / (111320 * Math.cos(lat * Math.PI / 180)), lat + metres * Math.cos(r) / 111320]
}
export const windLabel = (status: string) => status === 'clean' ? 'Away from mapped bedding' : status === 'scent_carries' ? 'Toward mapped bedding' : 'Direction uncertain'
// Theme tokens, so the map and the Stands page share one palette. Amber, not red:
// red is kept for safety, and a wrong wind is a reason to sit elsewhere, not a stop.
export const windToken = (status: string) => status === 'clean' ? '--v-best' : status === 'scent_carries' ? '--marginal' : '--v-quiet'
export const windColor = (status: string) => `var(${windToken(status)})`
export function windGeometry(stand: MapStand, fallbackRange: number) {
  const { lat, lon, wind } = stand
  // The API retains a fallback bearing for uncertain flow. Do not draw it as advice.
  if (lat == null || lon == null || wind.scent_bearing == null || wind.source === 'unknown' || !['clean', 'scent_carries'].includes(wind.status)) return null
  const range = wind.range_m ?? fallbackRange
  if (!Number.isFinite(range) || range <= 0) return null
  const bearing = wind.scent_bearing
  const half = wind.half_deg ?? 22.5
  const tip = offset(lat, lon, bearing, range * .82)
  const wing = Math.min(35, range * .1)
  // Arrowhead and shaft use geographic bearings, so they stay aligned when the map rotates.
  const arrow: GeoJSON.MultiLineString = { type: 'MultiLineString', coordinates: [
    [[lon, lat], tip],
    [offset(tip[1], tip[0], bearing + 150, wing), tip, offset(tip[1], tip[0], bearing + 210, wing)],
  ] }
  const ring: [number, number][] = [[lon, lat]]
  for (let i = 0; i <= 20; i++) ring.push(offset(lat, lon, bearing - half + 2 * half * i / 20, range))
  ring.push([lon, lat])
  return { arrow, cone: { type: 'Polygon', coordinates: [ring] } as GeoJSON.Polygon }
}

// ── measuring ──
// Distances on an estate are a few hundred metres, so a sphere is plenty and a flat
// projection around the shape's own latitude is plenty for areas.
export type LngLat = [number, number]
const EARTH_M = 6371008.8
const rad = (d: number) => d * Math.PI / 180
export function validLngLat(lon: unknown, lat: unknown): boolean {
  return typeof lon === 'number' && typeof lat === 'number' && Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
}
export function distanceM(a: LngLat, b: LngLat): number {
  const dLat = rad(b[1] - a[1]), dLon = rad(b[0] - a[0])
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_M * Math.asin(Math.min(1, Math.sqrt(h)))
}
/** Initial bearing from a to b, 0-360 clockwise from north. */
export function bearingDeg(a: LngLat, b: LngLat): number {
  const y = Math.sin(rad(b[0] - a[0])) * Math.cos(rad(b[1]))
  const x = Math.cos(rad(a[1])) * Math.sin(rad(b[1])) - Math.sin(rad(a[1])) * Math.cos(rad(b[1])) * Math.cos(rad(b[0] - a[0]))
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}
/** Area of an open ring (first corner not repeated) in square metres. */
export function areaM2(ring: LngLat[]): number {
  if (ring.length < 3) return 0
  const lat0 = rad(ring.reduce((sum, p) => sum + p[1], 0) / ring.length)
  const xy = ring.map(([lon, lat]) => [rad(lon) * EARTH_M * Math.cos(lat0), rad(lat) * EARTH_M])
  let twice = 0
  for (let i = 0; i < xy.length; i++) {
    const [x1, y1] = xy[i], [x2, y2] = xy[(i + 1) % xy.length]
    twice += x1 * y2 - x2 * y1
  }
  return Math.abs(twice) / 2
}
export const formatDistance = (m: number) => m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(m < 10_000 ? 1 : 0)} km`
export const formatArea = (m2: number) => m2 < 1000 ? `${Math.round(m2)} m²` : `${(m2 / 10_000).toFixed(1)} ha`
/** "134 m · north-east": how far, and which way to walk from the first point. */
export const measureLabel = (a: LngLat, b: LngLat) => `${formatDistance(distanceM(a, b))} · ${direction(bearingDeg(a, b))}`
export function circle(center: LngLat, radiusM: number, steps = 48): GeoJSON.Polygon {
  const ring: [number, number][] = []
  for (let i = 0; i <= steps; i++) ring.push(offset(center[1], center[0], 360 * i / steps, radiusM))
  return { type: 'Polygon', coordinates: [ring] }
}
