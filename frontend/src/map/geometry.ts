import { type Key, t } from '../i18n/core'
import { fmtNumber } from '../i18n/format'

// A camera as the map has it (GET /map/cameras): its newest photo worth showing,
// how many photos are new to you, and last night in visits, never in frames.
export type CameraHealth = {
  status: string; detail: string; producing: boolean; hours_since_report: number | null
  // With status not_syncing: the login that fetches this camera, and what is wrong with it.
  // `camera`: the login works, only this camera's photos could not be listed.
  login?: { label: string | null; error: string | null; camera?: boolean }
}
export type LatestPhoto = { image_id: string; captured_at: string; species_id: string | null; label: string }
export type Visits = { species_id: string | null; label: string; visits: number }
// How far to trust last night's list (routes_map.night_status): working, so an empty
// list is a quiet night; frames still being checked; frames the AI couldn't check at
// all; out of credits partway; or nothing sent and maybe not working. null is no
// record either way.
export type NightStatus = 'watched' | 'checking' | 'unreadable' | 'incomplete' | 'blind'
export type Camera = {
  id: string; name: string; lat: number | null; lon: number | null
  battery_pct: number | null; signal_pct: number | null; last_report_at: string | null
  health: CameraHealth; can_rename: boolean
  latest: LatestPhoto | null; new_count: number
  // Last night runs 18:00 to 08:00, as Activity and Replay count it; until 08:00 it is still going.
  last_night: Visits[]; last_night_status: NightStatus | null; last_night_so_far?: boolean
  // This camera's alert switch for you (false: muted), and whether your alerts are on at all.
  alerts: boolean; alerts_enabled: boolean
  // Placed by hand (its own GPS doesn't move it), and whether it has reported a position.
  location_is_custom?: boolean; provider_location?: boolean
}
export type Zone = { id: string; name: string; kind: string; polygon: GeoJSON.Polygon }
// `at_local`: the moment it is judged for (45 min after sunset, or `now` once dark).
export type WindReport = { status: string; text: string; scent_bearing?: number; speed_kmh?: number; range_m?: number; half_deg?: number; source?: string; at_local?: string; now?: boolean }
// The verdicts that are a call at a time. "Not on the map yet" and "No bedding drawn
// yet" are why there is none, and never say "for 20:39" as if they were one.
const CALLED_AT = new Set(['clean', 'scent_carries', 'too_light', 'no_wind_data'])
/** Whether a wind status is a call at a time, so the time it is for may be said. */
export const isCall = (status: string | null | undefined) => !!status && CALLED_AT.has(status)
/** When a stand's wind line is for: "for 20:39" or "now"; '' for a line that isn't a call. */
export const windFor = (w: WindReport, status = w.status) =>
  !isCall(status) ? '' : w.now ? t('wind.now') : w.at_local ? t('wind.forTime', { time: w.at_local }) : ''
// `claimed_tonight`/`claimed_by`: tonight's reservation, as Stands has it (an older
// server leaves them out, and the sheet then offers Reserve as it always did).
export type MapStand = { id: string; name: string; lat: number | null; lon: number | null; wind: WindReport; approaches: { zone: string; approach_deg: number; distance_m: number }[]; claimed_tonight?: boolean; claimed_by?: string | null }
export type MapData = {
  conditions: {
    wind_dir_deg: number | null; wind_speed_kmh: number | null
    // What the wind bar, the stands and the shading are judged for, and tonight's sunset.
    wind_at_local?: string; wind_now?: boolean; sunset_local?: string | null; sunset?: string | null
    forecast_fetched_at?: string | null; forecast_stale?: boolean
  }
  airflow: { source: string; wind_dir_deg: number | null; wind_speed_kmh: number | null; text?: string; confidence?: string }
  zones: Zone[]; stands: MapStand[]
  safe_ground: { status: string; cells: { lat: number; lon: number; safe: boolean }[]; note?: string }
  // Always empty now: the likely paths come from GET /map/paths (audit G-25).
  routes: unknown[]
  scent_range_m: number; terrain_loaded: boolean
  // Placed stands the hill shape doesn't reach (an older server leaves it out).
  terrain_outside?: string[]
}
// GET /map/paths: two cameras the replay linked on `nights` of the last month.
export type LikelyPath = {
  camera_ids: [string, string]; cameras: [string, string]
  from: { lat: number; lon: number }; to: { lat: number; lon: number }
  nights: number
  ways: { from_camera_id: string; to_camera_id: string; nights: number }[]
  species: { species_id: string; label: string; nights: number }[]
}
const POINTS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'] as const
const point = (degrees: number) => POINTS[Math.round(((degrees % 360) + 360) % 360 / 45) % 8]
/** "NW", in the language's own letters (Swedish "NV", Finnish "LU"). */
export const compass = (degrees: number) => t(`compass.${point(degrees)}` as Key)
// Compass words, not degrees. "From the north-west" reads at a glance. Each its own
// phrase: Finnish says "from" and "towards" with the word's own ending.
export const direction = (degrees: number) => t(`dir.${point(degrees)}` as Key)
/** "From the north-west": where the wind comes from. */
export const directionFrom = (degrees: number) => t(`dirFrom.${point(degrees)}` as Key)
/** "Scent goes south-east": where the wind takes a hunter's scent. */
export const scentTowards = (degrees: number) => t(`scentTo.${point(degrees)}` as Key)
export const downwind = (from: number) => (from + 180) % 360
export function offset(lat: number, lon: number, bearing: number, metres: number): [number, number] {
  const r = bearing * Math.PI / 180
  return [lon + metres * Math.sin(r) / (111320 * Math.cos(lat * Math.PI / 180)), lat + metres * Math.cos(r) / 111320]
}
export const windLabel = (status: string) => t(status === 'clean' ? 'wind.away' : status === 'scent_carries' ? 'wind.toward' : 'wind.uncertain')
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
const digits = (n: number) => ({ minimumFractionDigits: n, maximumFractionDigits: n })
export const formatDistance = (m: number) => m < 1000 ? `${fmtNumber(Math.round(m))} m` : `${fmtNumber(m / 1000, digits(m < 10_000 ? 1 : 0))} km`
export const formatArea = (m2: number) => m2 < 1000 ? `${fmtNumber(Math.round(m2))} m²` : `${fmtNumber(m2 / 10_000, digits(1))} ha`

// ── drawing an outline ──
// Closer than this to the last corner is the same corner pressed twice (a gloved
// double press), and closer than this to the first is the shape closing on itself.
const SAME_CORNER_M = 1
/** Whether `p` would be a real next corner, not a repeat of the last or the first. */
export function isNewCorner(points: LngLat[], p: LngLat): boolean {
  const last = points[points.length - 1]
  if (last && distanceM(last, p) < SAME_CORNER_M) return false
  return !(points.length > 1 && distanceM(points[0], p) < SAME_CORNER_M)
}
export const nearFirstCorner = (points: LngLat[], p: LngLat | null) => !!p && points.length > 2 && distanceM(points[0], p) < SAME_CORNER_M * 8
/**
 * Whether any two edges cross: a bow-tie, not an area (B-10). `closed` includes the
 * edge from the last corner back to the first, which Finish shape would draw.
 */
export function crossesItself(points: LngLat[], closed = true): boolean {
  const n = points.length
  const edges = closed ? n : n - 1
  if (n < 4) return false
  const k = Math.cos(rad(points[0][1]))
  const xy = points.map(([lon, lat]) => [lon * k, lat])
  const side = (a: number[], b: number[], c: number[]) => Math.sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
  for (let i = 0; i < edges; i++) {
    const a = xy[i], b = xy[(i + 1) % n]
    for (let j = i + 2; j < edges; j++) {
      if (closed && i === 0 && j === n - 1) continue // the two edges that meet at the first corner
      const c = xy[j], d = xy[(j + 1) % n]
      if (side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0) return true
    }
  }
  return false
}
/** "134 m · north-east": how far, and which way to walk from the first point. */
export const measureLabel = (a: LngLat, b: LngLat) => `${formatDistance(distanceM(a, b))} · ${direction(bearingDeg(a, b))}`
export function circle(center: LngLat, radiusM: number, steps = 48): GeoJSON.Polygon {
  const ring: [number, number][] = []
  for (let i = 0; i <= steps; i++) ring.push(offset(center[1], center[0], 360 * i / steps, radiusM))
  return { type: 'Polygon', coordinates: [ring] }
}
