import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { ageLabel, getFresh, noAnswerWords, savedCopy, thumbUrl, whenLabel, type StaleWhy } from '../api'
import CameraAlertRow from '../components/CameraAlerts'
import PhotoLightbox, { type LightboxPhoto } from '../components/PhotoLightbox'
import HighlightStrip, { NoteMark } from '../components/WorthALook'
import { cap, t, tn } from '../i18n'
import { validLngLat, type Camera } from './geometry'
import { stripPath } from './offline'
import { OwnGpsControl, RenameControl } from './PlaceSheet'

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
// of three frames is one tile, so it asks for enough frames to fill about 12 tiles
// (36: stripPath, the address "Download the estate" keeps it under).
const STRIP = 12
const LOAD_TIMEOUT_MS = 20_000

type Photo = {
  image_id: string; file_url: string; captured_at: string; camera: string; label: string; notes_count: number
  species_id?: string | null; fixed_by?: string | null
}
type Failure = Error & { offline?: boolean; timeout?: boolean }

const batteryWords = (pct: number | null) => t(pct == null ? 'camSheet.batteryUnknown' : pct < 20 ? 'cameras.h.battery' : pct < 50 ? 'camSheet.batteryHalf' : 'camSheet.batteryGood')
const signalWords = (pct: number | null) => pct == null ? null : t(pct < 30 ? 'camSheet.signalWeak' : pct < 60 ? 'camSheet.signalFair' : 'camSheet.signalStrong')
const visitWords = (n: number) => t('common.visits', { count: n })

type NightLine = { text: string; note: string | null; tone: 'plain' | 'quiet' | 'warn' }

/**
 * "Last night: Wild boar · 2 visits, Red deer · 1 visit", or why there is nothing to
 * say, with a note when the list may not be everything. An empty list only reads as
 * a quiet night when the camera was working and its photos have all been checked.
 * Last night runs to 08:00, as on Activity and Replay: before then it is "so far".
 */
export function lastNightLine(c: Camera): NightLine {
  const s = c.last_night_status
  const night = c.last_night_so_far ? t('camSheet.lastNightSoFar') : t('camSheet.lastNight')
  if (c.last_night.length) {
    const note = s === 'checking' ? t('camSheet.stillRest')
      : s === 'unreadable' ? t('camSheet.someUnchecked', { night })
      : s === 'incomplete' ? t('camSheet.outOfCredits') : null
    return { text: `${cap(night)}: ${c.last_night.map(v => `${v.label} · ${visitWords(v.visits)}`).join(', ')}`, note, tone: 'plain' }
  }
  if (s === 'checking') return { text: t('camSheet.stillChecking'), note: null, tone: 'quiet' }
  // Photos the AI gave up on are not "nothing there": a broken AI read as a quiet night.
  if (s === 'unreadable') return { text: t('camSheet.nothingFound', { night }), note: null, tone: 'warn' }
  if (s === 'incomplete') return { text: t('camSheet.nothingCredits', { night }), note: null, tone: 'warn' }
  // A camera that was down saw nothing because it couldn't, not because nothing came.
  const blind = s === 'blind' || (s == null && !c.health.producing)
  return blind
    ? { text: t('camSheet.blind'), note: null, tone: 'warn' }
    : { text: t('camSheet.nothing', { night }), note: null, tone: 'plain' }
}

/** What is wrong with the camera, in words, or null when it is working. A login that
 * stopped is said as such, with the way to Settings: the camera itself may be fine. */
function trouble(c: Camera): ReactNode | null {
  const h = c.health
  if (h.status === 'not_syncing') return <>
    {t('camSheet.notComing')} {h.login?.camera
      ? t('camSheet.couldntGet', { why: h.login.error ?? '' })
      : h.login?.error
        ? h.login.label ? t('cameras.loginNamed', { label: h.login.label, why: h.login.error }) : t('cameras.login', { why: h.login.error })
        : t('cameras.noFetch')}{' '}
    <Link className="map-link" to="/settings#accounts">{t('fresh.cameraLogins')}</Link>
  </>
  if (h.status === 'retired') return t('camSheet.retired')
  if (h.status === 'disconnected') return t('camSheet.disconnected')
  if (h.status === 'quiet') return t('camSheet.quiet', { detail: h.detail })
  if (h.status === 'offline') return c.last_report_at ? t('camSheet.offline', { ago: ageLabel(c.last_report_at) }) : t('camSheet.never')
  if (h.status === 'out_of_credits') return t('camSheet.credits')
  return null
}

export function CameraHeader({ camera }: { camera: Camera }) {
  const last = camera.latest ? t('camSheet.lastPhoto', { when: whenLabel(camera.latest.captured_at), ago: ageLabel(camera.latest.captured_at) }) : t('camSheet.noAnimalPhotos')
  return <>
    <span className="map-eyebrow">{t('map.camera')}</span>
    <h2 className="bsheet-name">{camera.name}</h2>
    <p className="bsheet-meta">{last}</p>
  </>
}

/** The camera's latest photos, newest first, each opening the photo viewer.
 * `notesTick` changes when a note is added or removed elsewhere on the sheet;
 * `onRetry` is its Try again, which the sheet also uses to ask for the team's marks.
 * What the phone saved (the estate downloaded for no signal, or this visit) paints
 * at once, and stays, with how old it is, when the answer doesn't come. */
function PhotoStrip({ camera, notesTick, onNotes, onRetry }: { camera: Camera; notesTick: number; onNotes: () => void; onRetry: () => void }) {
  const [photos, setPhotos] = useState<Photo[] | null>(null)
  const [stale, setStale] = useState<{ at: string; why?: StaleWhy } | null>(null)
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | null>(null)
  const request = useRef(0)
  // A fix in the viewer ("Wrong?"): the strip is asked again once the viewer closes.
  const fixed = useRef(false)
  // Asked again when a newer photo arrives, not on every map refresh.
  const newest = camera.latest?.image_id

  const load = useCallback(() => {
    const id = ++request.current
    setErr('')
    // Checked frames only, like the map's photo: an unchecked one is most likely grass.
    const path = stripPath(camera.id)
    let answered = false
    savedCopy<{ items: Photo[] }>(path).then(got => {
      if (got && !answered && id === request.current) setPhotos(ps => ps ?? got.data.items)
    })
    getFresh<{ items: Photo[] }>(path, { timeoutMs: LOAD_TIMEOUT_MS })
      .then(got => {
        answered = true
        if (id !== request.current) return
        setPhotos(got.data.items); setStale(got.stale ? { at: got.at, why: got.why } : null)
      })
      .catch((e: Failure) => {
        answered = true
        if (id !== request.current) return
        setErr(e.offline ? t('camSheet.photosNoSignal') : e.timeout ? t('camSheet.photosNoAnswer') : t('camSheet.photosCouldnt', { why: e.message }))
      })
  }, [camera.id])
  useEffect(() => { setPhotos(null); setStale(null); setZoom(null) }, [camera.id])
  useEffect(() => { load(); return () => { request.current++ } }, [load, newest, notesTick])

  // A refresh that fails keeps the photos already shown; only an empty strip says so.
  if (err && !photos) return <p className="map-inline-error cam-strip-msg" role="alert">{err} <button type="button" className="map-link" onClick={() => { load(); onRetry() }}>{t('common.tryAgain')}</button></p>
  if (!photos) return <p className="cam-strip-msg" role="status">{t('photos.loading')}</p>
  if (!photos.length) return <p className="cam-strip-msg">{t('camSheet.noneFromThis')}</p>
  const viewer: LightboxPhoto[] = photos.map(p => ({
    id: p.image_id, file_url: p.file_url, captured_at: p.captured_at, camera: p.camera, label: p.label,
    notes_count: p.notes_count, species_id: p.species_id, fixed_by: p.fixed_by,
  }))
  // One tile per burst (frames stamped the same second), opening on its first frame;
  // the viewer still pages through every frame.
  const tiles: { at: number; frames: number }[] = []
  photos.forEach((p, i) => {
    const last = tiles[tiles.length - 1]
    if (last && photos[last.at].captured_at === p.captured_at) last.frames++
    else tiles.push({ at: i, frames: 1 })
  })
  return <>
    {stale && <p className="cam-strip-msg cam-strip-age" role="status">{noAnswerWords(stale.why)} {t('camSheet.savedAgo', { ago: ageLabel(stale.at) })}</p>}
    <ul className="cam-strip-row" aria-label={t('camSheet.latestFrom', { name: camera.name })}>
      {tiles.slice(0, STRIP).map(({ at, frames }) => {
        const p = photos[at]
        // A note on any frame of the burst: often the second shows the animal best.
        const notes = photos.slice(at, at + frames).reduce((n, x) => n + (x.notes_count || 0), 0)
        return <li key={p.image_id}>
          {/* No "×3" on the tile: everywhere else that means three animals. The viewer
              pages through the burst's photos. */}
          <button type="button" className="cam-strip-tile" aria-label={frames > 1 ? t('camSheet.tileBurst', { label: p.label, when: whenLabel(p.captured_at), n: frames }) : t('camSheet.tile', { label: p.label, when: whenLabel(p.captured_at) })} onClick={() => setZoom(at)}>
            <img src={thumbUrl(p.image_id)} alt="" loading="lazy" decoding="async" draggable={false} />
            <NoteMark count={notes} />
            <span aria-hidden="true">{whenLabel(p.captured_at)}</span>
          </button>
        </li>
      })}
    </ul>
    {/* Over everything, the tab bar included: the sheet sits inside the map. */}
    {zoom != null && createPortal(<PhotoLightbox photos={viewer} start={zoom} backLabel={t('camSheet.backMap')}
      onClose={() => { setZoom(null); if (fixed.current) { fixed.current = false; load() } }}
      onFixed={() => { fixed.current = true }}
      onNotesChange={(id, n) => { setPhotos(ps => ps && ps.map(p => p.image_id === id ? { ...p, notes_count: n } : p)); onNotes() }} />, document.body)}
  </>
}

export function CameraBody({ camera, admin, onMove, onRename, onUseOwnGps, onAlerts }: {
  camera: Camera
  admin: boolean
  onMove: () => void
  onRename: (name: string) => Promise<void>
  /** Back to the position the camera itself reports. */
  onUseOwnGps: () => Promise<void>
  /** The camera's alert switch saved: keep the map's copy in step. */
  onAlerts: (alerts: boolean, enabled: boolean) => void
}) {
  const placed = validLngLat(camera.lon, camera.lat)
  const signal = signalWords(camera.signal_pct)
  const problem = trouble(camera)
  const night = lastNightLine(camera)
  const low = camera.battery_pct != null && camera.battery_pct < 20
  // A note added from the photo strip shows in the "Worth a look" strip, and back.
  const [notesTick, setNotesTick] = useState(0)
  const [stripTick, setStripTick] = useState(0)
  return <>
    {!placed && <p className="map-detail-copy">{t('standWind.no_position')}{admin ? '' : ` ${t('place.adminCan')}`}</p>}
    {problem && <p className="cam-sheet-status cam-sheet-status--warn">{problem}</p>}
    {/* Words first; the numbers are one tap away. */}
    <details className="cam-sheet-numbers">
      <summary className={low ? 'cam-sheet-status--warn' : undefined}>{batteryWords(camera.battery_pct)}{signal ? ` · ${signal}` : ''}</summary>
      <p>
        {camera.battery_pct == null ? t('camSheet.batteryUnknown') : t('camSheet.batteryPct', { pct: camera.battery_pct })}
        {camera.signal_pct != null && ` · ${t('camSheet.signalPct', { pct: camera.signal_pct })}`}
        {camera.last_report_at && ` · ${t('camSheet.checkedIn', { ago: ageLabel(camera.last_report_at) })}`}
      </p>
    </details>
    <p className={`cam-sheet-night${night.tone === 'plain' ? '' : ` cam-sheet-night--${night.tone}`}`}>
      {night.text}
      {night.note && <span className="cam-sheet-night-note">{night.note}</span>}
    </p>
    <PhotoStrip camera={camera} notesTick={stripTick} onNotes={() => setNotesTick(t => t + 1)} onRetry={() => setNotesTick(t => t + 1)} />
    <Link className="map-button map-button--primary map-button--big" to={`/photos?camera=${encodeURIComponent(camera.id)}`}>{t('camSheet.seeAll')}</Link>
    <div className="cam-sheet-alerts">
      <CameraAlertRow id={camera.id} name={camera.name} alerts={camera.alerts} label={t('camSheet.alerts')}
        note={camera.alerts ? t('camSheet.alertsOn') : t('camSheet.alertsMuted')}
        onSaved={r => onAlerts(r.alerts, r.enabled)} />
      {!camera.alerts_enabled && <p className="cam-sheet-alerts-off">
        {tn('camSheet.alertsOff', { link: <Link to="/settings#notifications">{t('camSheet.turnOn')}</Link> })}
      </p>}
    </div>
    {(admin || camera.can_rename) && <div className="map-actions map-actions--admin">
      {admin && <button type="button" className="map-button" onClick={onMove}>{placed ? t('place.move') : t('place.placeIt')}</button>}
      {camera.can_rename && <RenameControl name={camera.name} onRename={onRename} maxLength={100} />}
    </div>}
    {admin && camera.location_is_custom && camera.provider_location && <OwnGpsControl onUse={onUseOwnGps} />}
    {/* Last on the sheet: it arrives on its own answer, and arriving above the buttons
        would move them under a thumb. Asked again with the photo strip (a note changed
        there, its Try again) and when the camera has a newer photo. Quiet when it fails:
        the photo strip already says there's no signal. */}
    <HighlightStrip className="cam-sheet-wal" cameraId={camera.id} limit={12} refreshKey={`${notesTick}:${camera.latest?.image_id ?? ''}`} backLabel={t('camSheet.backMap')}
      quietErrors onChange={() => setStripTick(t => t + 1)} />
  </>
}
