import { getFresh, getToken, thumbUrl } from '../api'
import { MAX_ZOOM, TILES, type BaseId } from './basemaps'
import type { Camera } from './geometry'

/**
 * The estate saved on this phone, for a valley with no signal (feature 24, audit B-06).
 *
 * One action, "Download the estate for offline", keeps:
 *   - the chosen base map's pictures over the estate's box (an admin's, or one drawn
 *     round everything placed: GET /estate), at the zooms a hunter uses, within a
 *     size budget;
 *   - the stands, cameras, bedding and tonight's map (the service worker keeps
 *     /map/tonight and /map/cameras whenever the map loads; this asks for them
 *     fresh), the likely paths, and each camera's sheet: its photo strip, the
 *     team's marked photos and their small photos.
 * The service worker (public/sw.js) answers from ESTATE_CACHE when there is no
 * signal: map pictures and small photos first from there, the rest when the network
 * fails. A note of what was saved, and when, is kept in the same store.
 *
 * Only IGN's bases are saved. They are free public services, reused with credit,
 * and a few hundred pictures over one estate is what a hunter's phone would ask for
 * by using the map there anyway. Esri's terms don't allow offline copies of its
 * imagery, so "Aerial (world)" isn't offered. Nothing outside the box, and nothing
 * closer than the level a phone uses on a stand (18 for the aerial, the topo's own 17).
 */
export const ESTATE_CACHE = 'gamesense-estate-v1'
// A key in the store, never a URL the server has: what was saved and when.
const NOTE_KEY = '/__gamesense/estate-offline.json'

export type Box = { south: number; west: number; north: number; east: number }
export type EstateBox = { box: Box; box_set: boolean; box_set_at: string | null; box_km: [number, number] }
export type Saved = {
  base: BaseId; box: Box; minZoom: number; maxZoom: number
  tiles: number; missing: number; bytes: number; photos: number; at: string
  // Cut short by the size budget (the box an admin set is bigger than planned).
  capped?: boolean
}
export type Plan = { base: BaseId; box: Box; minZoom: number; maxZoom: number; tiles: number; bytes: number }
export type Progress = { done: number; total: number; bytes: number; stage: 'map' | 'sheets' }

export const SAVABLE: BaseId[] = ['aerial', 'topo']
// Zoom 11 shows the whole estate and the villages round it; 18 is a stand's tree.
const MIN_ZOOM = 11
const TOP_ZOOM: Record<BaseId, number> = { aerial: 18, topo: Math.min(17, MAX_ZOOM.topo), world: 0 }
// What one picture weighs, about: PNOA's JPEG over scrub and fields, MTN's flatter topo.
const TILE_BYTES: Record<BaseId, number> = { aerial: 25_000, topo: 15_000, world: 25_000 }
// The plan stays under this; a download stops at the hard cap whatever the pictures weigh.
export const PLAN_BYTES = 60 * 1024 * 1024
const HARD_CAP_BYTES = 100 * 1024 * 1024
const MAX_TILES = 4000
// Four at a time: quick on a good link, and polite to a free public service.
const PARALLEL = 4
const TILE_TIMEOUT_MS = 20_000

// ── which pictures ──

const lonToX = (lon: number, z: number) => Math.floor((lon + 180) / 360 * 2 ** z)
const latToY = (lat: number, z: number) => {
  const r = lat * Math.PI / 180
  return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * 2 ** z)
}
const clampTile = (v: number, z: number) => Math.min(2 ** z - 1, Math.max(0, v))

/** The x and y ranges of the pictures that cover `box` at zoom `z` (XYZ, as the map asks). */
export function tileRange(box: Box, z: number) {
  return {
    x0: clampTile(lonToX(box.west, z), z), x1: clampTile(lonToX(box.east, z), z),
    y0: clampTile(latToY(box.north, z), z), y1: clampTile(latToY(box.south, z), z),
  }
}
export function countTiles(box: Box, minZoom: number, maxZoom: number): number {
  let n = 0
  for (let z = minZoom; z <= maxZoom; z++) {
    const r = tileRange(box, z)
    n += (r.x1 - r.x0 + 1) * (r.y1 - r.y0 + 1)
  }
  return n
}
export const tileUrl = (base: BaseId, z: number, x: number, y: number) =>
  TILES[base].replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y))

/** The zooms to save for `box`: from the estate's overview in as close as the budget allows. */
export function plan(box: Box, base: BaseId): Plan {
  let maxZoom = MIN_ZOOM
  for (let z = MIN_ZOOM; z <= TOP_ZOOM[base]; z++) {
    const n = countTiles(box, MIN_ZOOM, z)
    if (n > MAX_TILES || n * TILE_BYTES[base] > PLAN_BYTES) break
    maxZoom = z
  }
  const tiles = countTiles(box, MIN_ZOOM, maxZoom)
  return { base, box, minZoom: MIN_ZOOM, maxZoom, tiles, bytes: tiles * TILE_BYTES[base] }
}

function* tilesOf(p: Plan) {
  for (let z = p.minZoom; z <= p.maxZoom; z++) {
    const r = tileRange(p.box, z)
    for (let x = r.x0; x <= r.x1; x++) for (let y = r.y0; y <= r.y1; y++) yield tileUrl(p.base, z, x, y)
  }
}

// ── what is saved ──

const hasStore = () => typeof caches !== 'undefined'

export async function readSaved(): Promise<Saved | null> {
  try {
    if (!hasStore()) return null
    const hit = await caches.match(NOTE_KEY, { cacheName: ESTATE_CACHE })
    return hit ? (await hit.json()) as Saved : null
  } catch {
    return null
  }
}

export async function removeSaved(): Promise<void> {
  if (hasStore()) await caches.delete(ESTATE_CACHE)
}

/** "38 MB", "900 KB". */
export function sizeLabel(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${Math.round(bytes / (1024 * 1024))} MB`
}

/** Whether two boxes are the same ground, to a few metres. */
export const sameBox = (a: Box, b: Box) =>
  (['south', 'west', 'north', 'east'] as const).every(k => Math.abs(a[k] - b[k]) < 1e-4)

// ── saving it ──

const stamp = () => new Date().toISOString()
// Keys as the store gives them back: whole addresses.
const href = (url: string) => new URL(url, location.origin).href
const bytesOf = (res: Response | undefined) => Number(res?.headers.get('X-GameSense-Bytes') || 0)

/** Where the phone is short of room, in words, or null when there is room. */
async function roomFor(bytes: number): Promise<string | null> {
  try {
    const est = await navigator.storage?.estimate?.()
    if (!est?.quota) return null
    const free = est.quota - (est.usage ?? 0)
    return free < bytes * 1.2 ? `Not enough room on this phone: about ${sizeLabel(bytes)} is needed and ${sizeLabel(Math.max(0, free))} is free.` : null
  } catch {
    return null
  }
}

async function fetchTile(url: string, signal: AbortSignal): Promise<Blob | null> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const ctl = new AbortController()
    const stop = () => ctl.abort()
    signal.addEventListener('abort', stop, { once: true })
    const timer = setTimeout(stop, TILE_TIMEOUT_MS)
    try {
      // 'reload': past the saved copy (the service worker's) to the network.
      const res = await fetch(url, { mode: 'cors', cache: 'reload', signal: ctl.signal })
      const blob = res.ok ? await res.blob() : null
      // A tile service's error is a small XML page, not a picture.
      if (blob && blob.type.startsWith('image/')) return blob
    } catch {
      if (signal.aborted) throw new DOMException('Stopped', 'AbortError')
    } finally {
      clearTimeout(timer)
      signal.removeEventListener('abort', stop)
    }
  }
  return null
}

/** One same-site answer, kept under its own address, marked with when. */
async function keepJson(cache: Cache, path: string, signal: AbortSignal): Promise<unknown> {
  const token = getToken()
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, signal })
  if (!res.ok || res.headers.get('X-GameSense-Stale')) return null
  const body = await res.text()
  await cache.put(`/api${path}`, new Response(body, {
    headers: { 'Content-Type': 'application/json', 'X-GameSense-Cached-At': stamp(), 'X-GameSense-Bytes': String(body.length) },
  }))
  return JSON.parse(body)
}

/** A small photo, kept under its address without the sign-in token (which changes). */
async function keepThumb(cache: Cache, id: string, signal: AbortSignal): Promise<number> {
  const key = `/api/images/${id}/thumb`
  const had = await cache.match(key)
  if (had) return bytesOf(had)
  const res = await fetch(thumbUrl(id), { signal })
  if (!res.ok) return 0
  const blob = await res.blob()
  await cache.put(key, new Response(blob, { headers: { 'Content-Type': blob.type || 'image/webp', 'X-GameSense-Bytes': String(blob.size) } }))
  return blob.size
}

// The camera sheet's own questions (map/CameraSheet.tsx, components/WorthALook.tsx):
// the same addresses, so the sheet finds them with no signal.
export const stripPath = (cameraId: string) => `/photos?cameras=${encodeURIComponent(cameraId)}&limit=36&checked=true`
export const marksPath = (cameraId: string) => `/photos/highlights?${new URLSearchParams({ limit: '12', camera_id: cameraId })}`

/**
 * Save the estate. Pictures already saved are kept (a second download fills the
 * gaps a weak link left); pictures and answers from an older box or base go.
 * Throws Error with words a hunter reads; an AbortError when stopped.
 */
export async function download({ base, box, cameras, signal, onProgress }: {
  base: BaseId; box: Box; cameras: Camera[]; signal: AbortSignal; onProgress: (p: Progress) => void
}): Promise<Saved> {
  if (!hasStore()) throw new Error('This browser can’t save the map on this phone.')
  if (!SAVABLE.includes(base)) throw new Error('That map type can’t be saved on a phone.')
  const p = plan(box, base)
  const short = await roomFor(p.bytes)
  if (short) throw new Error(short)
  // Ask the phone not to clear it when it runs short of room. It may say no.
  navigator.storage?.persist?.().catch(() => false)
  const cache = await caches.open(ESTATE_CACHE)
  const wanted = new Set<string>()
  let done = 0, bytes = 0, missing = 0, capped = false

  // The map's pictures, overview first, so a stop part way still leaves a usable map.
  const urls = [...tilesOf(p)]
  const queue = urls.slice()
  const report = () => onProgress({ done, total: urls.length, bytes, stage: 'map' })
  report()
  const worker = async () => {
    for (let url = queue.shift(); url; url = queue.shift()) {
      if (signal.aborted) throw new DOMException('Stopped', 'AbortError')
      if (bytes > HARD_CAP_BYTES) { capped = true; return }
      wanted.add(href(url))
      const had = await cache.match(url)
      if (had) bytes += bytesOf(had)
      else {
        const blob = await fetchTile(url, signal)
        if (blob) {
          await cache.put(url, new Response(blob, { headers: { 'Content-Type': blob.type, 'X-GameSense-Bytes': String(blob.size) } }))
          bytes += blob.size
        } else missing++
      }
      done++
      if (done % 8 === 0 || done === urls.length) report()
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker))
  if (missing === urls.length) throw new Error('No map pictures came through. Check the signal and try again.')

  // Tonight's map, the cameras and each camera's sheet.
  onProgress({ done: 0, total: cameras.length + 2, bytes, stage: 'sheets' })
  await Promise.all([getFresh('/map/tonight', { save: true, timeoutMs: 30_000 }), getFresh('/map/cameras', { save: true, timeoutMs: 30_000 })])
    .catch(() => { throw new Error('The stands and cameras didn’t load. Check the signal and try again.') })
  let photos = 0
  const keep = async (path: string) => {
    wanted.add(href(`/api${path}`))
    const answer = await keepJson(cache, path, signal)
    bytes += bytesOf(await cache.match(`/api${path}`))
    return answer
  }
  await keep('/map/paths').catch(() => null)
  await keep('/estate').catch(() => null)
  let sheets = 0
  for (const cam of cameras) {
    if (signal.aborted) throw new DOMException('Stopped', 'AbortError')
    const ids = new Set<string>(cam.latest ? [cam.latest.image_id] : [])
    const strip = await keep(stripPath(cam.id)).catch(() => null) as { items?: { image_id: string }[] } | null
    const marks = await keep(marksPath(cam.id)).catch(() => null) as { items?: { image_id?: string; id?: string }[] } | null
    strip?.items?.forEach(x => ids.add(x.image_id))
    marks?.items?.forEach(x => { const id = x.image_id ?? x.id; if (id) ids.add(id) })
    for (const id of ids) {
      wanted.add(href(`/api/images/${id}/thumb`))
      const n = await keepThumb(cache, id, signal).catch(() => 0)
      if (n) { photos++; bytes += n }
    }
    onProgress({ done: ++sheets + 2, total: cameras.length + 2, bytes, stage: 'sheets' })
  }

  // What an older box, base or camera left behind goes.
  wanted.add(href(NOTE_KEY))
  for (const req of await cache.keys()) if (!wanted.has(req.url)) await cache.delete(req)
  const saved: Saved = { base, box, minZoom: p.minZoom, maxZoom: p.maxZoom, tiles: done - missing, missing, bytes, photos, at: stamp(), ...(capped ? { capped } : {}) }
  await cache.put(NOTE_KEY, new Response(JSON.stringify(saved), { headers: { 'Content-Type': 'application/json' } }))
  return saved
}
