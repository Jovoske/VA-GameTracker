import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { ageLabel, api, thumbUrl } from '../api'
import PhotoLightbox, { type LightboxPhoto } from '../components/PhotoLightbox'
import { validLngLat, type Camera } from './geometry'
import { RenameControl } from './PlaceSheet'

/**
 * A camera's sheet on the map: what it saw, whether it is working, and its photos.
 *
 * The header is what shows at the 112px peek, so it carries the one line that says
 * the most: when the camera last had an animal on it. Below that, the camera's
 * battery and signal in words, last night counted in visits (a burst of three
 * frames of one boar is one visit), and a strip of its latest photos that open the
 * photo viewer. Opening this sheet is what clears the camera's "new" count, and
 * the page does that, not this file.
 */

// The strip is a glance, not the gallery: "See all photos" is the gallery. A burst
// of three frames is one tile, so it asks for enough frames to fill about 12 tiles.
const STRIP = 12
const FRAMES = 36
const LOAD_TIMEOUT_MS = 20_000

type Photo = { image_id: string; file_url: string; captured_at: string; camera: string; label: string }
type Failure = Error & { offline?: boolean; timeout?: boolean }

/** "21:40" today, "Tue 21:40" this week, "4 Sep 21:40" before that. */
export function whenLabel(iso: string): string {
  const d = new Date(iso)
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  const days = (Date.now() - d.getTime()) / 86_400_000
  if (d.toDateString() === new Date().toDateString()) return time
  if (days < 6) return `${d.toLocaleDateString(undefined, { weekday: 'short' })} ${time}`
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${time}`
}

const batteryWords = (pct: number | null) => pct == null ? 'Battery unknown' : pct < 20 ? 'Battery low' : pct < 50 ? 'Battery half' : 'Battery good'
const signalWords = (pct: number | null) => pct == null ? null : pct < 30 ? 'Signal weak' : pct < 60 ? 'Signal fair' : 'Signal strong'
const visitWords = (n: number) => `${n} visit${n === 1 ? '' : 's'}`

/** "Last night: Wild boar · 2 visits, Red deer · 1 visit", or why there is nothing to say. */
export function lastNightLine(c: Camera): { text: string; warn: boolean } {
  if (c.last_night.length) return { text: `Last night: ${c.last_night.map(v => `${v.label} · ${visitWords(v.visits)}`).join(', ')}`, warn: false }
  // A camera that was down saw nothing because it couldn't, not because nothing came.
  const blind = c.last_night_watched === false || (c.last_night_watched == null && !c.health.producing)
  return blind
    ? { text: 'No photos from last night. The camera may not have been working, so that isn’t a quiet night.', warn: true }
    : { text: 'Nothing on camera last night', warn: false }
}

/** What is wrong with the camera, in words, or null when it is working. */
function trouble(c: Camera): string | null {
  if (c.health.status === 'offline') return c.last_report_at ? `Not checking in. Last heard from ${ageLabel(c.last_report_at)}.` : 'It has never checked in.'
  if (c.health.status === 'out_of_credits') return 'Out of photo credits. New photos won’t come through until the plan renews.'
  return null
}

export function CameraHeader({ camera }: { camera: Camera }) {
  const last = camera.latest ? `Last photo ${whenLabel(camera.latest.captured_at)} (${ageLabel(camera.latest.captured_at)})` : 'No animal photos yet'
  return <>
    <span className="map-eyebrow">Camera</span>
    <h2 className="bsheet-name">{camera.name}</h2>
    <p className="bsheet-meta">{last}</p>
  </>
}

/** The camera's latest photos, newest first, each opening the photo viewer. */
function PhotoStrip({ camera }: { camera: Camera }) {
  const [photos, setPhotos] = useState<Photo[] | null>(null)
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | null>(null)
  const request = useRef(0)
  // Asked again when a newer photo arrives, not on every map refresh.
  const newest = camera.latest?.image_id

  const load = useCallback(() => {
    const id = ++request.current
    setErr('')
    api<{ items: Photo[] }>(`/photos?cameras=${encodeURIComponent(camera.id)}&limit=${FRAMES}`, { timeoutMs: LOAD_TIMEOUT_MS })
      .then(page => { if (id === request.current) setPhotos(page.items) })
      .catch((e: Failure) => {
        if (id !== request.current) return
        setErr(e.offline ? 'No signal, so the photos didn’t load.' : e.timeout ? 'No answer from the server, so the photos didn’t load.' : `Couldn’t load the photos. ${e.message}`)
      })
  }, [camera.id])
  useEffect(() => { setPhotos(null); setZoom(null) }, [camera.id])
  useEffect(() => { load(); return () => { request.current++ } }, [load, newest])

  // A refresh that fails keeps the photos already shown; only an empty strip says so.
  if (err && !photos) return <p className="map-inline-error cam-strip-msg" role="alert">{err} <button type="button" className="map-link" onClick={load}>Try again</button></p>
  if (!photos) return <p className="cam-strip-msg" role="status">Loading photos…</p>
  if (!photos.length) return <p className="cam-strip-msg">No animal photos from this camera yet.</p>
  const viewer: LightboxPhoto[] = photos.map(p => ({ id: p.image_id, file_url: p.file_url, captured_at: p.captured_at, camera: p.camera, label: p.label }))
  // One tile per burst (frames stamped the same second), opening on its first frame;
  // the viewer still pages through every frame.
  const tiles: { at: number; frames: number }[] = []
  photos.forEach((p, i) => {
    const last = tiles[tiles.length - 1]
    if (last && photos[last.at].captured_at === p.captured_at) last.frames++
    else tiles.push({ at: i, frames: 1 })
  })
  return <>
    <ul className="cam-strip-row" aria-label={`Latest photos from ${camera.name}`}>
      {tiles.slice(0, STRIP).map(({ at, frames }) => {
        const p = photos[at]
        return <li key={p.image_id}>
          <button type="button" className="cam-strip-tile" aria-label={`${p.label}, ${whenLabel(p.captured_at)}${frames > 1 ? `, ${frames} frames` : ''}. Open photo.`} onClick={() => setZoom(at)}>
            <img src={thumbUrl(p.image_id)} alt="" loading="lazy" decoding="async" draggable={false} />
            <span aria-hidden="true">{whenLabel(p.captured_at)}{frames > 1 && <b>×{frames}</b>}</span>
          </button>
        </li>
      })}
    </ul>
    {/* Over everything, the tab bar included: the sheet sits inside the map. */}
    {zoom != null && createPortal(<PhotoLightbox photos={viewer} start={zoom} backLabel={`Back to ${camera.name}`} onClose={() => setZoom(null)} />, document.body)}
  </>
}

export function CameraBody({ camera, admin, onMove, onRename }: {
  camera: Camera
  admin: boolean
  onMove: () => void
  onRename: (name: string) => Promise<void>
}) {
  const placed = validLngLat(camera.lon, camera.lat)
  const signal = signalWords(camera.signal_pct)
  const problem = trouble(camera)
  const night = lastNightLine(camera)
  const low = camera.battery_pct != null && camera.battery_pct < 20
  return <>
    {!placed && <p className="map-detail-copy">Not on the map yet.{admin ? '' : ' An admin can place it.'}</p>}
    {problem && <p className="cam-sheet-status cam-sheet-status--warn">{problem}</p>}
    {/* Words first; the numbers are one tap away. */}
    <details className="cam-sheet-numbers">
      <summary className={low ? 'cam-sheet-status--warn' : undefined}>{batteryWords(camera.battery_pct)}{signal ? ` · ${signal}` : ''}</summary>
      <p>
        Battery {camera.battery_pct == null ? 'unknown' : `${camera.battery_pct}%`}
        {camera.signal_pct != null && ` · Signal ${camera.signal_pct}%`}
        {camera.last_report_at && ` · Checked in ${ageLabel(camera.last_report_at)}`}
      </p>
    </details>
    <p className={`cam-sheet-night${night.warn ? ' cam-sheet-night--warn' : ''}`}>{night.text}</p>
    <PhotoStrip camera={camera} />
    <Link className="map-button map-button--primary map-button--big" to={`/photos?camera=${encodeURIComponent(camera.id)}`}>See all photos</Link>
    {(admin || camera.can_rename) && <div className="map-actions map-actions--admin">
      {admin && <button type="button" className="map-button" onClick={onMove}>{placed ? 'Move' : 'Place it on the map'}</button>}
      {camera.can_rename && <RenameControl name={camera.name} onRename={onRename} maxLength={100} />}
    </div>}
  </>
}
