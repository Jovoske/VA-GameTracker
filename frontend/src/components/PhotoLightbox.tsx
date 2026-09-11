import { DownloadSimpleIcon } from '@phosphor-icons/react/dist/csr/DownloadSimple'
import { MagnifyingGlassMinusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassMinus'
import { MagnifyingGlassPlusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassPlus'
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { imageUrl } from '../api'
import { useReducedMotion } from '../hooks'
import Overlay from './Overlay'

/**
 * The one photo viewer. Cameras, the species gallery on Animals and the class
 * gallery on Insights all open photos through this, so paging, zoom, download
 * and the back button behave the same everywhere. There used to be three: one
 * with paging and two that were a bare <img> you could only look at.
 */

export type LightboxPhoto = {
  id: string
  file_url: string
  captured_at: string
  camera: string
  /** What is in the frame: "Stag", "Sow + piglets (4)", "No animal detected". */
  label: string
}

/**
 * Where the photo sits on the stage: scale, and offset from centre in px.
 * `snap` is true for a jump the user asked for (double-tap, button, key) and
 * false while a finger is driving it — one animates, the other must not lag.
 */
type View = { s: number; x: number; y: number; snap: boolean }
const FIT: View = { s: 1, x: 0, y: 0, snap: true }
const MAX_ZOOM = 6
const TAP_ZOOM = 2.5
type Pt = { x: number; y: number }
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y)
const mid = (a: Pt, b: Pt): Pt => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

/** `PL19_2026-09-04_22-05.jpg`: the camera and the moment, in local time. */
function downloadName(cam: string, capturedAt: string): string {
  const d = new Date(capturedAt)
  const p = (n: number) => String(n).padStart(2, '0')
  const stem = cam.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'camera'
  return `${stem}_${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}.jpg`
}

export default function PhotoLightbox({
  photos,
  start = 0,
  backLabel,
  zIndex,
  onClose,
}: {
  photos: LightboxPhoto[]
  start?: number
  backLabel: string
  zIndex?: number
  onClose: () => void
}) {
  const [idx, setIdx] = useState(Math.min(Math.max(0, start), photos.length - 1))
  const im = photos[idx]
  const [imgReady, setImgReady] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [saving, setSaving] = useState(false)
  const reduced = useReducedMotion()
  const [view, setView] = useState<View>(FIT)
  const viewRef = useRef(view)
  viewRef.current = view
  const stageRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const swipe = useRef<{ x: number; t: number } | null>(null)
  // Every finger currently on the stage, by pointer id.
  const pointers = useRef(new Map<number, Pt>())
  // q0: the photo point (fit-scale px from its centre) that was under the fingers' midpoint.
  const pinch = useRef<{ d0: number; q0: Pt; s0: number } | null>(null)
  const pan = useRef<{ x: number; y: number; v0: View; moved: boolean } | null>(null)
  const lastTap = useRef<{ t: number; x: number; y: number } | null>(null)

  // Keyboard: ← → to move, + − 0 to zoom. Escape belongs to Overlay, so that
  // every panel in the app answers it rather than only this one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') step(-1)
      if (e.key === 'ArrowRight') step(1)
      if (e.key === '+' || e.key === '=') setView((v) => zoomAt(v.s * 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '-') setView((v) => zoomAt(v.s / 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '0') setView(FIT)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx])

  // Wheel zoom wants preventDefault (ctrl+wheel would otherwise zoom the whole
  // page), and React registers wheel as passive, so this one is bound by hand.
  useEffect(() => {
    const st = stageRef.current
    if (!st) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = viewRef.current
      // A trackpad pinch arrives as ctrl+wheel in small deltas, a mouse wheel in
      // big steps; exp() makes both feel proportional.
      setView(zoomAt(v.s * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), local(e.clientX, e.clientY), v, false))
    }
    st.addEventListener('wheel', onWheel, { passive: false })
    return () => st.removeEventListener('wheel', onWheel)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Move through the photos, stopping at both ends. */
  function step(d: number) {
    const i = idx + d
    if (i < 0 || i >= photos.length) return
    // The next photo fades in once it has actually decoded. Swapping src alone
    // gave a blank frame and then a jump as the stage resized to fit it.
    setImgReady(false)
    setImgError(false)
    setView(FIT)
    setIdx(i)
  }

  /** A pointer position in stage-centre coordinates, which is where the photo's transform is anchored. */
  function local(clientX: number, clientY: number): Pt {
    const r = stageRef.current?.getBoundingClientRect()
    if (!r) return { x: 0, y: 0 }
    return { x: clientX - (r.left + r.width / 2), y: clientY - (r.top + r.height / 2) }
  }

  /** Keep the photo on the stage: it may only slide as far as it overflows, and at fit it stays centred. */
  function clampView(v: View): View {
    const s = Math.min(MAX_ZOOM, Math.max(1, v.s))
    const st = stageRef.current
    const el = imgRef.current
    if (!st || !el) return { ...v, s }
    const ox = Math.max(0, (el.offsetWidth * s - st.clientWidth) / 2)
    const oy = Math.max(0, (el.offsetHeight * s - st.clientHeight) / 2)
    return { ...v, s, x: Math.min(ox, Math.max(-ox, v.x)), y: Math.min(oy, Math.max(-oy, v.y)) }
  }

  /** Put photo point `q` (fit-scale px from its centre) under stage point `m`, at scale `s`. */
  function place(s: number, q: Pt, m: Pt, snap: boolean): View {
    s = Math.min(MAX_ZOOM, Math.max(1, s))
    return clampView({ s, x: m.x - s * q.x, y: m.y - s * q.y, snap })
  }

  /** Rescale so the bit of photo under `p` stays put. */
  function zoomAt(s: number, p: Pt, from: View, snap: boolean): View {
    return place(s, { x: (p.x - from.x) / from.s, y: (p.y - from.y) / from.s }, p, snap)
  }

  /**
   * Swipe to turn the page — on a phone this is the whole navigation, and two
   * 46px arrows were standing in for it. A flick counts even when it barely
   * moves: past 0.11 px/ms the intent is unambiguous, which is the same
   * threshold a drag-to-dismiss uses.
   *
   * Once zoomed in, the same finger pans the photo instead, and two fingers
   * pinch. A double-tap toggles between fit and a close look at that spot.
   */
  function pointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* pointer already gone */
    }
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const v = viewRef.current
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const m = local(mid(a, b).x, mid(a, b).y)
      pinch.current = { d0: Math.max(1, dist(a, b)), q0: { x: (m.x - v.x) / v.s, y: (m.y - v.y) / v.s }, s0: v.s }
      pan.current = null
      swipe.current = null
    } else if (pointers.current.size === 1) {
      pan.current = { x: e.clientX, y: e.clientY, v0: v, moved: false }
      swipe.current = { x: e.clientX, t: e.timeStamp }
    }
  }

  function pointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(e.pointerId)) return
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const g = pinch.current
    if (g && pointers.current.size >= 2) {
      const [a, b] = [...pointers.current.values()]
      const m = mid(a, b)
      setView(place(g.s0 * (dist(a, b) / g.d0), g.q0, local(m.x, m.y), false))
      return
    }
    const p = pan.current
    if (p && viewRef.current.s > 1) {
      const dx = e.clientX - p.x
      const dy = e.clientY - p.y
      if (Math.abs(dx) + Math.abs(dy) > 4) p.moved = true
      setView(clampView({ ...p.v0, x: p.v0.x + dx, y: p.v0.y + dy, snap: false }))
    }
  }

  function pointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(e.pointerId)
    if (pinch.current) {
      if (pointers.current.size >= 2) return
      pinch.current = null
      // Let go with barely any zoom left and it means "back to fit".
      const v = viewRef.current.s < 1.05 ? FIT : viewRef.current
      setView(v)
      // A finger still down carries on as a pan from where it is now.
      const [rest] = [...pointers.current.values()]
      pan.current = rest ? { x: rest.x, y: rest.y, v0: v, moved: true } : null
      swipe.current = null
      return
    }
    const p = pan.current
    pan.current = null
    if (viewRef.current.s > 1) {
      if (p && !p.moved) tap(e)
      return
    }
    const s = swipe.current
    swipe.current = null
    if (!s) return
    const dx = e.clientX - s.x
    const dt = Math.max(1, e.timeStamp - s.t)
    if (Math.abs(dx) < 12) {
      tap(e)
      return
    }
    if (Math.abs(dx) > 60 || Math.abs(dx) / dt > 0.11) step(dx < 0 ? 1 : -1)
  }

  function pointerCancel(e: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    if (pointers.current.size === 0) {
      pan.current = null
      swipe.current = null
    }
  }

  /** Two taps on the same spot within a third of a second: zoom in there, or back out. */
  function tap(e: ReactPointerEvent<HTMLDivElement>) {
    const l = lastTap.current
    if (l && e.timeStamp - l.t < 320 && Math.hypot(e.clientX - l.x, e.clientY - l.y) < 24) {
      lastTap.current = null
      const v = viewRef.current
      setView(v.s > 1 ? FIT : zoomAt(TAP_ZOOM, local(e.clientX, e.clientY), v, true))
      return
    }
    lastTap.current = { t: e.timeStamp, x: e.clientX, y: e.clientY }
  }

  function toggleZoom() {
    const v = viewRef.current
    setView(v.s > 1 ? FIT : zoomAt(TAP_ZOOM, { x: 0, y: 0 }, v, true))
  }

  async function download() {
    if (saving) return
    const src = imageUrl(im.file_url)
    const name = downloadName(im.camera, im.captured_at)
    setSaving(true)
    try {
      // On a phone the share sheet is where "Save Image" lives; a download link
      // on iOS opens the photo in a tab the user then has to find a way out of.
      if (navigator.share && navigator.canShare && window.matchMedia('(pointer: coarse)').matches) {
        try {
          const blob = await (await fetch(src)).blob()
          const file = new File([blob], name, { type: 'image/jpeg' })
          if (navigator.canShare({ files: [file] })) {
            await navigator.share({ files: [file], title: name })
            return
          }
        } catch (e) {
          if ((e as Error).name === 'AbortError') return // sheet dismissed: not an error
        }
      }
      // Everywhere else: the server marks it as an attachment and names it.
      const a = document.createElement('a')
      a.href = `${src}${src.includes('?') ? '&' : '?'}download=1`
      a.download = name
      document.body.appendChild(a)
      a.click()
      a.remove()
    } finally {
      setSaving(false)
    }
  }

  const when = new Date(im.captured_at).toLocaleString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })

  return (
    <Overlay
      label={`${im.camera} · Photo ${idx + 1} of ${photos.length}`}
      backLabel={backLabel}
      onClose={onClose}
      backdrop="rgba(0, 0, 0, 0.92)"
      zIndex={zIndex}
      style={{ flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 12 }}
      tools={
        // The two things you do with a photo once it is big: get closer, and keep it.
        <>
          <button
            className="ov-tool"
            onClick={toggleZoom}
            aria-label={view.s > 1 ? 'Fit photo to screen' : 'Zoom in'}
            title={view.s > 1 ? 'Fit to screen' : 'Zoom in — or double-tap, pinch, or scroll on the photo'}
          >
            {view.s > 1 ? <MagnifyingGlassMinusIcon size={20} /> : <MagnifyingGlassPlusIcon size={20} />}
          </button>
          <button className="ov-tool" onClick={download} disabled={saving} aria-label="Download photo" title="Download photo">
            <DownloadSimpleIcon size={20} />
          </button>
        </>
      }
    >
      {(_close) => (
        <>
          {/* A stage of fixed size. Photos come off the cameras at mixed aspect
              ratios, and letting each one set the frame meant the picture jumped
              around the screen as you paged through. */}
          <div
            ref={stageRef}
            className="ov-panel lb-stage"
            onClick={(e) => e.stopPropagation()}
            onPointerDown={pointerDown}
            onPointerMove={pointerMove}
            onPointerUp={pointerUp}
            onPointerCancel={pointerCancel}
            style={{ cursor: view.s > 1 ? 'grab' : 'default' }}
          >
            {imgError && <div role="alert" className="lb-status">Could not load this photo. Try another photo or go back.</div>}
            {!imgReady && !imgError && <span role="status" className="lb-status">Loading photo…</span>}
            <img
              ref={imgRef}
              key={im.id}
              src={imageUrl(im.file_url)}
              alt={im.label}
              draggable={false}
              onLoad={() => setImgReady(true)}
              onError={() => setImgError(true)}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                borderRadius: 'var(--r-ctl)',
                opacity: imgReady ? 1 : 0,
                transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`,
                transition:
                  view.snap && !reduced
                    ? 'opacity var(--d-fast) var(--ease-out), transform var(--d-base) var(--ease-out)'
                    : 'opacity var(--d-fast) var(--ease-out)',
                willChange: 'transform',
                display: imgError ? 'none' : undefined,
              }}
            />
          </div>
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              marginTop: 10, display: 'flex', alignItems: 'center', gap: 12,
              background: 'rgba(0,0,0,0.55)', borderRadius: 'var(--r-ctl)', padding: '8px 14px',
              fontSize: 13, color: '#fff', maxWidth: '94vw', flexWrap: 'wrap', justifyContent: 'center',
            }}
          >
            <b>{im.camera}</b>
            <span>{im.label}</span>
            <span style={{ opacity: 0.75 }}>{when}</span>
            <span style={{ opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
              {idx + 1} / {photos.length}
            </span>
          </div>
          <button
            className="lb-nav"
            style={{ left: 8 }}
            disabled={idx === 0}
            onClick={(e) => { e.stopPropagation(); step(-1) }}
            aria-label="Previous photo"
          >
            ‹
          </button>
          <button
            className="lb-nav"
            style={{ right: 8 }}
            disabled={idx === photos.length - 1}
            onClick={(e) => { e.stopPropagation(); step(1) }}
            aria-label="Next photo"
          >
            ›
          </button>
        </>
      )}
    </Overlay>
  )
}
