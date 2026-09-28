import { BinocularsIcon } from '@phosphor-icons/react/dist/csr/Binoculars'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { getFresh, savedCopy, thumbUrl } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { t } from '../i18n'
import { noteSnippet, type Highlight } from '../notes'
import type { PhotoFix } from './PhotoFix'
import PhotoLightbox from './PhotoLightbox'

type Failure = Error & { offline?: boolean; timeout?: boolean }

// The last answer per strip (every camera, or one), for this visit to the app: going
// back to Photos shows it at once, in its place, while it is asked again.
const lastAnswer = new Map<string, Highlight[]>()
// Whether a strip had anything last time, kept on the phone: then its place is held
// while it loads, so it doesn't push the grid down under a thumb when it arrives.
const HAD = 'gs.wal.had:'
function hadMarks(key: string): boolean {
  try { return localStorage.getItem(HAD + key) === '1' } catch { return false }
}
function rememberMarks(key: string, had: boolean) {
  try { localStorage.setItem(HAD + key, had ? '1' : '0') } catch { /* private mode: nothing to hold */ }
}

/**
 * "Worth a look": the photos the team marked, the most recently marked first, each
 * with the newest thing said about it, and who said it and when. On Photos it
 * covers every camera; on a camera's sheet, that camera. Nothing shows until
 * something has been marked.
 *
 * Tapping one opens the photo viewer over the strip, where the notes can be read in
 * full and added to, and a wrong animal fixed. The strip asks again once the viewer
 * closes if anything changed there, whenever `refreshKey` changes (a note added from
 * the grid), and on coming back to the app, when a teammate may have marked something
 * meanwhile. A fix is passed on (`onFixed`, then `onClosed`) so the page's own list,
 * which may show the same photo, follows it too.
 *
 * While the first answer is on its way the strip holds its place if it had photos
 * last time, and takes none if it didn't, so a late answer doesn't move what is
 * already under a thumb.
 */
export default function HighlightStrip({ cameraId, refreshKey = 0, backLabel, limit = 20, onChange, onFixed, onClosed, className, quietErrors = false }: {
  cameraId?: string
  refreshKey?: string | number
  backLabel: string
  limit?: number
  /** A note was added or removed in the viewer opened from here. */
  onChange?: (imageId: string, count: number) => void
  /** "Wrong?" in the viewer opened from here changed what a photo is. */
  onFixed?: (imageId: string, fix: PhotoFix) => void
  /** That viewer closed: a list can drop the photos a fix took out of it now. */
  onClosed?: () => void
  className?: string
  /** Say nothing when it can't load: something else on the screen already says why. */
  quietErrors?: boolean
}) {
  const key = cameraId ?? 'all'
  const [items, setItems] = useState<Highlight[] | null>(() => lastAnswer.get(key) ?? null)
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | null>(null)
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  const changed = useRef(false)
  const request = useRef(0)

  const load = useCallback(() => {
    const id = ++request.current
    setErr('')
    // The same address "Download the estate" keeps a camera's under (offline.ts marksPath).
    const q = new URLSearchParams({ limit: String(limit) })
    if (cameraId) q.set('camera_id', cameraId)
    const path = `/photos/highlights?${q}`
    // What the phone saved paints at once when this visit has nothing yet: on a link
    // that hangs the answer takes the whole timeout, then falls back to it anyway.
    let answered = false
    savedCopy<{ items: Highlight[] }>(path).then((got) => {
      if (got && !answered && id === request.current) setItems((was) => was ?? got.data.items)
    })
    getFresh<{ items: Highlight[] }>(path, { timeoutMs: 20_000 })
      .then(({ data: r, stale }) => {
        answered = true
        if (id !== request.current) return
        setItems(r.items)
        if (stale) return
        lastAnswer.set(key, r.items)
        rememberMarks(key, r.items.length > 0)
      })
      .catch((e: Failure) => {
        answered = true
        if (id !== request.current) return
        setErr(e.offline ? t('wal.noSignal') : e.timeout ? t('wal.noAnswer') : t('wal.couldnt', { why: e.message }))
      })
  }, [cameraId, limit, key])

  useEffect(() => { setItems(lastAnswer.get(key) ?? null); setZoom(null) }, [key])
  // Not while the viewer is open: its photos would change under the finger.
  useEffect(() => { if (zoom == null) load() }, [load, refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { request.current++ }, [])
  useRefetchOnReturn(() => { if (zoomRef.current == null) load() }, 120_000)

  // A failed refresh keeps the strip already shown; only a first load that fails says so.
  if (err && !items) return quietErrors ? null : <p className={`wal-msg${className ? ` ${className}` : ''}`} role="alert">{err} <button type="button" className="wal-retry" onClick={load}>{t('common.tryAgain')}</button></p>
  if (!items) return hadMarks(key) ? <HeldPlace className={className} withCamera={!cameraId} /> : null
  if (items.length === 0) return null
  return (
    <section className={`wal${className ? ` ${className}` : ''}`} aria-label={t('notes.worthALook')}>
      <h2 className="sect wal-head">
        <BinocularsIcon size={16} aria-hidden="true" /> {t('notes.worthALook')}
        <span className="sect-note">{t('wal.byTeam')}</span>
      </h2>
      <ul className="wal-row">
        {items.map((h, i) => {
          // What was said leads, then who said it and when (the note's time, not the
          // photo's); what is in it sits on the photo, and on Photos the camera last.
          const { said, who } = noteSnippet(h.notes)
          return (
            <li key={h.image_id}>
              <button type="button" className="wal-tile" onClick={() => setZoom(i)}
                aria-label={t(said ? 'wal.tileSaid' : 'wal.tileMarked', { what: cameraId ? h.label : t('wal.atCamera', { label: h.label, camera: h.camera }), said: said ?? '', who })}>
                <span className="wal-img">
                  <img src={thumbUrl(h.image_id)} alt="" loading="lazy" decoding="async" draggable={false} />
                  <NoteMark count={h.notes_count} />
                  <span className="wal-tag" aria-hidden="true">{h.label}</span>
                </span>
                <span className={`wal-note${said ? '' : ' wal-note--bare'}`} aria-hidden="true">{said ?? t('wal.noNote')}</span>
                <span className="wal-who" aria-hidden="true">{who}</span>
                {!cameraId && <span className="wal-meta" aria-hidden="true">{h.camera}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      {zoom != null && createPortal(
        <PhotoLightbox
          photos={items.map((h) => ({
            id: h.image_id, file_url: h.file_url, captured_at: h.captured_at, camera: h.camera, label: h.label,
            notes_count: h.notes_count, species_id: h.species_id, fixed_by: h.fixed_by,
          }))}
          start={zoom}
          backLabel={backLabel}
          zIndex={70}
          onClose={() => {
            setZoom(null)
            if (changed.current) { changed.current = false; load() }
            onClosed?.()
          }}
          onNotesChange={(id, n) => { changed.current = true; onChange?.(id, n) }}
          onFixed={(id, fix) => { changed.current = true; onFixed?.(id, fix) }}
        />,
        document.body,
      )}
    </section>
  )
}

/** The strip's place while it loads: the same heading and tile boxes, empty. */
function HeldPlace({ className, withCamera }: { className?: string; withCamera: boolean }) {
  return (
    <section className={`wal wal--held${className ? ` ${className}` : ''}`} aria-hidden="true">
      <h2 className="sect wal-head">
        <BinocularsIcon size={16} aria-hidden="true" /> {t('notes.worthALook')}
        <span className="sect-note">{t('wal.byTeam')}</span>
      </h2>
      <ul className="wal-row">
        {[0, 1, 2].map((i) => (
          <li key={i}>
            <span className="wal-tile">
              <span className="wal-img"><span className="wal-held-img" /></span>
              <span className="wal-note">&nbsp;</span>
              <span className="wal-who">&nbsp;</span>
              {withCamera && <span className="wal-meta">&nbsp;</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The small binoculars on a photo's tile when the team has notes on it. */
export function NoteMark({ count }: { count: number | undefined }) {
  if (!count) return null
  return (
    <span className="note-mark" title={t('wal.teamNotes', { count })}>
      <BinocularsIcon size={12} weight="bold" aria-hidden="true" />
      {count > 1 && <b>{count}</b>}
      <span className="sr-only">{t('wal.teamNotes', { count })}</span>
    </span>
  )
}
