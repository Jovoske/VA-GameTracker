import type { Map as MlMap } from 'maplibre-gl'
import { type Key, fmtDate, fmtNumber, t } from '../i18n'
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
export const VIEWS: { id: View; label: Key; note: Key }[] = [
  { id: 'cameras', label: 'nav.cameras', note: 'view.camerasNote' },
  { id: 'activity', label: 'view.activity', note: 'view.activityNote' },
  { id: 'replay', label: 'view.replay', note: 'view.replayNote' },
]
export const isView = (v: string | null): v is View => VIEWS.some(x => x.id === v)

// ── activity ──
export type Part = 'all' | 'dusk' | 'night' | 'dawn'
export type Nights = 1 | 7 | 30
export const PERIODS: { id: Nights; label: Key }[] = [
  { id: 1, label: 'night.lastNight' }, { id: 7, label: 'activity.7nights' }, { id: 30, label: 'activity.30nights' },
]
export const PARTS: { id: Part; label: Key; hours: string }[] = [
  { id: 'all', label: 'activity.allNight', hours: '18–08' },
  { id: 'dusk', label: 'activity.dusk', hours: '18–22' },
  { id: 'night', label: 'activity.night', hours: '22–03' },
  { id: 'dawn', label: 'activity.dawn', hours: '03–08' },
]
export type SpeciesVisits = { species_id: string | null; label: string; visits: number }
export type ActivityCamera = {
  camera_id: string; name: string; lat: number | null; lon: number | null
  visits: number; watched_nights: number; blind_nights: number; checking_nights: number
  // Nights left out because the AI couldn't check some of their photos.
  unreadable_nights?: number
  nights_with: number; per_night: number | null; peak: string | null
  by_species: SpeciesVisits[]; read: string
}
export type Activity = {
  nights: Nights; part: Part; species: string; species_label: string | null
  /** so_far: last night hasn't reached 08:00 yet, so its count is still growing. */
  first_night: string; last_night: string; so_far: boolean
  species_options: SpeciesVisits[]; cameras: ActivityCamera[]
}
export type ActivityFilters = { nights: Nights; part: Part; species: string }
export const DEFAULT_FILTERS: ActivityFilters = { nights: 7, part: 'all', species: 'all' }
export const activityPath = (f: ActivityFilters) => `/map/activity?species=${encodeURIComponent(f.species)}&part=${f.part}&nights=${f.nights}`

// Circle AREA is visits a night, so a camera with four times the visits reads as
// four times the ink, not sixteen. At 1 a night the radius is 12 px. Big feeders
// stop growing at 10 a night (38 px) so they don't bury the cameras around them,
// and nothing is smaller than 8 px, so every circle shows around its camera's 12 px dot.
const R_ONE = 12
export const TOP_RATE = 10
const R_MAX = R_ONE * Math.sqrt(TOP_RATE)
const R_MIN = 8
// A camera that was working and saw nothing: an empty ring just round its dot.
const R_QUIET = 9
// A camera whose photos are still being checked: a faint ring a little wider.
const R_CHECKING = 13
export const circleRadius = (perNight: number) => Math.min(R_MAX, Math.max(R_MIN, R_ONE * Math.sqrt(perNight)))
// The legend's two sizes: a round number at or above the busiest camera, and one
// about a fifth of it, so both circles in the key look like circles on the map.
// Never below 1 every 2 nights: smaller rates all get the smallest circle. Never
// above TOP_RATE: circles stop growing there, so the key says "10+ a night".
const LADDER = [0.5, 1, 2, 5, TOP_RATE]
export function legendSizes(max: number): [number, number] {
  const big = LADDER.findIndex(v => v >= max)
  const i = big < 0 ? LADDER.length - 1 : Math.max(2, big)
  return [LADDER[i - 2], LADDER[i]]
}
/** "2 a night", "0.8 a night", "1 every 3 nights": never "every 1 nights". In a
 *  sentence (`inSentence`), "one every 3 nights". */
export function rateWords(perNight: number, inSentence = false): string {
  if (!(perNight > 0)) return t('rate.none')
  const every = Math.round(1 / perNight)
  return every >= 2 ? t(inSentence ? 'rate.everyInSentence' : 'rate.every', { n: every })
    : t('rate.perNight', { n: fmtNumber(Math.round(perNight * 10) / 10) })
}

/** The activity circles (GL layers 'activity-circles', 'activity-quiet' and 'activity-checking'). */
export function drawActivity(map: MlMap, data: Activity | null, picked: string | null) {
  const features: GeoJSON.Feature[] = []
  for (const c of data?.cameras ?? []) {
    if (!validLngLat(c.lon, c.lat)) continue
    const geometry: GeoJSON.Point = { type: 'Point', coordinates: [c.lon!, c.lat!] }
    const base = { id: c.camera_id, picked: c.camera_id === picked }
    // A camera that was working and saw nothing is a real zero: a small empty ring.
    // One whose photos are still with the detector gets a faint ring until they are
    // checked. One that wasn't working gets no mark at all; its card says why.
    if (c.per_night != null) features.push({ type: 'Feature', geometry, properties: { ...base, mark: c.visits ? 'visits' : 'quiet', r: c.visits ? circleRadius(c.per_night) : R_QUIET } })
    else if (c.checking_nights) features.push({ type: 'Feature', geometry, properties: { ...base, mark: 'checking', r: R_CHECKING } })
  }
  setSource(map, 'activity', features)
}

// ── replay ──
export type ReplayVisit = { at: string; last_at: string; camera_id: string; species_id: string | null; label: string; group_size: number; frames: number; image_id: string }
export type ReplayLink = { from_camera_id: string; to_camera_id: string; species_id: string; label: string; from_at: string; to_at: string }
export type Replay = { night: string; start: string; end: string; visits: ReplayVisit[]; links: ReplayLink[] }
/** so_far: last night, before 08:00, when it is still going. */
export type ReplayNight = { night: string; visits: number; so_far?: boolean }
/** Minutes of the night that pass in one second of playback. Real time would take 14 hours. */
export const SPEEDS: { id: number; label: string; note: Key }[] = [
  { id: 1, label: '1×', note: 'replay.speed1' },
  { id: 10, label: '10×', note: 'replay.speed10' },
  { id: 60, label: '60×', note: 'replay.speed60' },
]
export const minutesInto = (iso: string, start: string) => (Date.parse(iso) - Date.parse(start)) / 60_000
const pad = (n: number) => String(n).padStart(2, '0')
/** 24-hour clock, as the rest of the map ("mostly 21–23 h"). */
export const clock = (ms: number) => { const d = new Date(ms); return `${pad(d.getHours())}:${pad(d.getMinutes())}` }
export function nightLabel(night: string, first: boolean, soFar = false): string {
  const { prefix, day } = nightParts(night, first, soFar)
  return prefix ? `${prefix} · ${day}` : day
}
/** nightLabel in its two parts, for a picker that lets "Last night" go first on a
 *  narrow phone rather than the date it is there to show. */
export function nightParts(night: string, first: boolean, soFar = false): { prefix: string | null; day: string } {
  const day = fmtDate(new Date(`${night}T12:00:00`), { weekday: 'short', day: 'numeric', month: 'short' })
  return { prefix: first ? (soFar ? t('replay.lastNightSoFar') : t('night.lastNight')) : null, day }
}
/**
 * The hours under the timeline: every third hour on the clock (18, 21, 00, 03, 06)
 * and the end, each at its minute of the night. Read off the clock, not fixed
 * steps: the nights the clocks change are 13 and 15 hours long.
 */
export function hourMarks(start: string, end: string): { m: number; label: string }[] {
  const s = Date.parse(start), e = Date.parse(end), out: { m: number; label: string }[] = []
  for (let t = s; t < e; t += 3_600_000) {
    const h = new Date(t).getHours()
    if (h % 3 === 0 && !out.some(x => x.label === pad(h))) out.push({ m: (t - s) / 60_000, label: pad(h) })
  }
  out.push({ m: (e - s) / 60_000, label: pad(new Date(e).getHours()) })
  return out
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
