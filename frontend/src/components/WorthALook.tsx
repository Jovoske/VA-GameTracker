import { BinocularsIcon } from '@phosphor-icons/react/dist/csr/Binoculars'
import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, thumbUrl } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { noteSnippet, type Highlight } from '../notes'
import PhotoLightbox from './PhotoLightbox'

type Failure = Error & { offline?: boolean; timeout?: boolean }

/**
 * "Worth a look": the photos the team marked, the most recently marked first, each
 * with the newest thing said about it, and who said it and when. On Photos it
 * covers every camera; on a camera's sheet, that camera. Nothing shows until
 * something has been marked.
 *
 * Tapping one opens the photo viewer over the strip, where the notes can be read in
 * full and added to. The strip asks again once the viewer closes if anything
 * changed there, whenever `refreshKey` changes (a note added from the grid), and
 * on coming back to the app, when a teammate may have marked something meanwhile.
 */
export default function HighlightStrip({ cameraId, refreshKey = 0, backLabel, limit = 20, onChange, className }: {
  cameraId?: string
  refreshKey?: string | number
  backLabel: string
  limit?: number
  /** A note was added or removed in the viewer opened from here. */
  onChange?: (imageId: string, count: number) => void
  className?: string
}) {
  const [items, setItems] = useState<Highlight[] | null>(null)
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | null>(null)
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  const changed = useRef(false)
  const request = useRef(0)

  const load = useCallback(() => {
    const id = ++request.current
    setErr('')
    const q = new URLSearchParams({ limit: String(limit) })
    if (cameraId) q.set('camera_id', cameraId)
    api<{ items: Highlight[] }>(`/photos/highlights?${q}`, { timeoutMs: 20_000 })
      .then((r) => { if (id === request.current) setItems(r.items) })
      .catch((e: Failure) => {
        if (id !== request.current) return
        setErr(e.offline ? 'No signal, so the team’s marked photos didn’t load.' : e.timeout ? 'No answer from the server, so the team’s marked photos didn’t load.' : `Couldn’t load the team’s marked photos. ${e.message}`)
      })
  }, [cameraId, limit])

  useEffect(() => { setItems(null); setZoom(null) }, [cameraId])
  // Not while the viewer is open: its photos would change under the finger.
  useEffect(() => { if (zoom == null) load() }, [load, refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { request.current++ }, [])
  useRefetchOnReturn(() => { if (zoomRef.current == null) load() }, 120_000)

  // A failed refresh keeps the strip already shown; only a first load that fails says so.
  if (err && !items) return <p className={`wal-msg${className ? ` ${className}` : ''}`} role="alert">{err} <button type="button" className="wal-retry" onClick={load}>Try again</button></p>
  if (!items || items.length === 0) return null
  return (
    <section className={`wal${className ? ` ${className}` : ''}`} aria-label="Worth a look">
      <h2 className="sect wal-head">
        <BinocularsIcon size={16} aria-hidden="true" /> Worth a look
        <span className="sect-note">marked by the team</span>
      </h2>
      <ul className="wal-row">
        {items.map((h, i) => {
          // What was said leads, then who said it and when (the note's time, not the
          // photo's); what is in it sits on the photo, and on Photos the camera last.
          const { said, who } = noteSnippet(h.notes)
          return (
            <li key={h.image_id}>
              <button type="button" className="wal-tile" onClick={() => setZoom(i)}
                aria-label={`${h.label}${cameraId ? '' : ` at ${h.camera}`}. ${said ? `“${said}”, ` : 'Marked, '}${who}. Open photo.`}>
                <span className="wal-img">
                  <img src={thumbUrl(h.image_id)} alt="" loading="lazy" decoding="async" draggable={false} />
                  <NoteMark count={h.notes_count} />
                  <span className="wal-tag" aria-hidden="true">{h.label}</span>
                </span>
                <span className={`wal-note${said ? '' : ' wal-note--bare'}`} aria-hidden="true">{said ?? 'Marked, no note'}</span>
                <span className="wal-who" aria-hidden="true">{who}</span>
                {!cameraId && <span className="wal-meta" aria-hidden="true">{h.camera}</span>}
              </button>
            </li>
          )
        })}
      </ul>
      {zoom != null && createPortal(
        <PhotoLightbox
          photos={items.map((h) => ({ id: h.image_id, file_url: h.file_url, captured_at: h.captured_at, camera: h.camera, label: h.label, notes_count: h.notes_count }))}
          start={zoom}
          backLabel={backLabel}
          zIndex={70}
          onClose={() => {
            setZoom(null)
            if (changed.current) { changed.current = false; load() }
          }}
          onNotesChange={(id, n) => { changed.current = true; onChange?.(id, n) }}
        />,
        document.body,
      )}
    </section>
  )
}

/** The small binoculars on a photo's tile when the team has notes on it. */
export function NoteMark({ count }: { count: number | undefined }) {
  if (!count) return null
  return (
    <span className="note-mark" title={`${count} team note${count === 1 ? '' : 's'}`}>
      <BinocularsIcon size={12} weight="bold" aria-hidden="true" />
      {count > 1 && <b>{count}</b>}
      <span className="sr-only">{count} team note{count === 1 ? '' : 's'}</span>
    </span>
  )
}
