export type Camera = { id: string; name: string; lat: number | null; lng: number | null; sightings: number; battery_pct: number | null }
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
export const downwind = (from: number) => (from + 180) % 360
export function offset(lat: number, lon: number, bearing: number, metres: number): [number, number] {
  const r = bearing * Math.PI / 180
  return [lon + metres * Math.sin(r) / (111320 * Math.cos(lat * Math.PI / 180)), lat + metres * Math.cos(r) / 111320]
}
export const windLabel = (status: string) => status === 'clean' ? 'Away from mapped bedding' : status === 'scent_carries' ? 'Toward mapped bedding' : 'Direction uncertain'
export const windColor = (status: string) => status === 'clean' ? '#a6c7b1' : status === 'scent_carries' ? '#e2ad83' : '#a2aaa5'
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
