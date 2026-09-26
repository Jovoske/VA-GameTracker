import type { Map as MlMap } from 'maplibre-gl'
import { setSource } from './layers'
import { bearingDeg, distanceM, offset, validLngLat, type LngLat } from './geometry'

/**
 * The map's two views of the cameras' visits, besides each camera's photo:
 *
 * - Activity ("where the game is"): a circle at each camera whose area is visits
 *   per night the camera was working (GET /map/activity).
 * - Replay: one night's visits in order on a timeline, 18:00 to 08:00, with a
 *   dashed arrow where the same species likely went on to the next camera
 *   (GET /map/replay).
 *
 * A visit is an arrival, never a frame: the server collapses bursts the same way
 * everywhere, so these agree with the camera sheet's "Last night".
 */
export type View = 'cameras' | 'activity' | 'replay'
export const VIEWS: { id: View; label: string; note: string }[] = [
  { id: 'cameras', label: 'Cameras', note: 'Each camera’s latest photo, and what is new to you.' },
  { id: 'activity', label: 'Activity', note: 'Where the game is: visits a night at each camera.' },
  { id: 'replay', label: 'Replay', note: 'Play a night back, camera by camera.' },
]
export const isView = (v: string | null): v is View => VIEWS.some(x => x.id === v)

// ── activity ──
export type Part = 'all' | 'dusk' | 'night' | 'dawn'
export type Nights = 1 | 7 | 30
export const PERIODS: { id: Nights; label: string }[] = [
  { id: 1, label: 'Last night' }, { id: 7, label: '7 nights' }, { id: 30, label: '30 nights' },
]
export const PARTS: { id: Part; label: string; hours: string }[] = [
  { id: 'all', label: 'All night', hours: '18–08' },
  { id: 'dusk', label: 'Dusk', hours: '18–22' },
  { id: 'night', label: 'Night', hours: '22–03' },
  { id: 'dawn', label: 'Dawn', hours: '03–08' },
]
export type SpeciesVisits = { species_id: string | null; label: string; visits: number }
export type ActivityCamera = {
  camera_id: string; name: string; lat: number | null; lon: number | null
  visits: number; watched_nights: number; blind_nights: number; checking_nights: number
  nights_with: number; per_night: number | null; peak: string | null
  by_species: SpeciesVisits[]; read: string
}
export type Activity = {
  nights: Nights; part: Part; species: string; species_label: string | null
  first_night: string; last_night: string
  species_options: SpeciesVisits[]; cameras: ActivityCamera[]
}
export type ActivityFilters = { nights: Nights; part: Part; species: string }
export const DEFAULT_FILTERS: ActivityFilters = { nights: 7, part: 'all', species: 'all' }
export const activityPath = (f: ActivityFilters) => `/map/activity?species=${encodeURIComponent(f.species)}&part=${f.part}&nights=${f.nights}`

// Circle AREA is visits a night, so a camera with four times the visits reads as
// four times the ink, not sixteen. At 1 a night the radius is 12 px. Big feeders
// stop growing at 38 px so they don't bury the cameras around them, and nothing is
// smaller than 8 px, so every circle shows around its camera's 12 px dot.
const R_ONE = 12
const R_MAX = 38
const R_MIN = 8
// A camera that was working and saw nothing: an empty ring just round its dot.
const R_QUIET = 9
export const circleRadius = (perNight: number) => Math.min(R_MAX, Math.max(R_MIN, R_ONE * Math.sqrt(perNight)))
// The legend's two sizes: a round number at or above the busiest camera, and one
// about a fifth of it, so both circles in the key look like circles on the map.
// Never below 1 every 2 nights: smaller rates all get the smallest circle.
const LADDER = [0.5, 1, 2, 5, 10, 20]
export function legendSizes(max: number): [number, number] {
  const big = LADDER.findIndex(v => v >= max)
  const i = big < 0 ? LADDER.length - 1 : Math.max(2, big)
  return [LADDER[i - 2], LADDER[i]]
}
export const rateWords = (perNight: number) =>
  perNight >= 1 ? `${perNight % 1 ? perNight.toFixed(1) : perNight} a night` : `1 every ${Math.round(1 / perNight)} nights`

/** The activity circles (GL layers 'activity-circles' and 'activity-quiet'). */
export function drawActivity(map: MlMap, data: Activity | null, picked: string | null) {
  const features: GeoJSON.Feature[] = []
  for (const c of data?.cameras ?? []) {
    if (!validLngLat(c.lon, c.lat) || c.per_night == null) continue
    const geometry: GeoJSON.Point = { type: 'Point', coordinates: [c.lon!, c.lat!] }
    // A camera that was working and saw nothing is a real zero: a small empty ring.
    // One that wasn't working gets no mark at all; its card says why.
    features.push({ type: 'Feature', geometry, properties: {
      id: c.camera_id, quiet: c.visits === 0, r: c.visits ? circleRadius(c.per_night) : R_QUIET, picked: c.camera_id === picked,
    } })
  }
  setSource(map, 'activity', features)
}

// ── replay ──
export type ReplayVisit = { at: string; last_at: string; camera_id: string; species_id: string | null; label: string; group_size: number; frames: number; image_id: string }
export type ReplayLink = { from_camera_id: string; to_camera_id: string; species_id: string; label: string; from_at: string; to_at: string }
export type Replay = { night: string; start: string; end: string; visits: ReplayVisit[]; links: ReplayLink[] }
export type ReplayNight = { night: string; visits: number }
/** Minutes of the night that pass in one second of playback. Real time would take 14 hours. */
export const SPEEDS: { id: number; label: string; note: string }[] = [
  { id: 1, label: '1×', note: 'An hour in a minute' },
  { id: 10, label: '10×', note: 'An hour in 6 seconds' },
  { id: 60, label: '60×', note: 'An hour a second' },
]
export const minutesInto = (iso: string, start: string) => (Date.parse(iso) - Date.parse(start)) / 60_000
const pad = (n: number) => String(n).padStart(2, '0')
/** 24-hour clock, as the rest of the map ("mostly 21–23 h"). */
export const clock = (ms: number) => { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}` }
export function nightLabel(night: string, first: boolean): string {
  const d = new Date(`${night}T12:00:00`)
  const day = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
  return first ? `Last night · ${day}` : day
}

/**
 * A faint dashed arrow from one camera to the next, short of both pins so it
 * doesn't hide them, with its head at the second camera. `o` is its opacity.
 */
export function linkArrow(from: LngLat, to: LngLat, o: number): GeoJSON.Feature[] {
  const length = distanceM(from, to)
  if (length < 30) return []
  const b = bearingDeg(from, to)
  const trim = Math.min(60, length * .18)
  const a = offset(from[1], from[0], b, trim), z = offset(from[1], from[0], b, length - trim)
  const wing = Math.min(28, length * .12)
  return [
    { type: 'Feature', properties: { o, part: 'shaft' }, geometry: { type: 'LineString', coordinates: [a, z] } },
    { type: 'Feature', properties: { o, part: 'head' }, geometry: { type: 'LineString', coordinates: [offset(z[1], z[0], b + 150, wing), z, offset(z[1], z[0], b + 210, wing)] } },
  ]
}
