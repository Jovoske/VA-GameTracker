import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { t } from '../i18n'

export type Snap = 'peek' | 'half' | 'full'
const ORDER: Snap[] = ['peek', 'half', 'full']
const PEEK = 112
// Matches --d-base in theme.css: the sheet has to outlive its close for this long.
const EXIT_MS = 200

/**
 * The sheet that slides up over the map when you tap something on it.
 *
 * Three resting heights: a 112px peek that keeps the map in view, half, and 90%.
 * Drag the handle (or the title row) to move between them, flick to jump, drag
 * below the peek to close. It lives inside the map stage, so on a phone it can
 * never slide over the tab bar.
 *
 * Not modal: the map above it stays live, so focus is moved into the sheet when it
 * opens and handed back when it closes, but not trapped. Escape closes it unless a
 * full-screen overlay (the photo viewer) is on top, which gets the key instead, or
 * the hunter is typing in it: then Escape only leaves the field and keeps the text.
 *
 * `onHeight` reports the visible height on every change, dragging included, so the
 * floating buttons can ride on top of it.
 */
export default function BottomSheet({ label, snap, onSnap, onClose, onHeight, header, children, focusKey, returnFocus }: {
  label: string
  snap: Snap
  onSnap: (snap: Snap) => void
  onClose: () => void
  onHeight?: (px: number, snap: Snap) => void
  header: ReactNode
  children: ReactNode
  /** Change it to move focus into the sheet again, e.g. when a pin is chosen. A new
   * value also cancels a close in progress, so give each choice its own, even a
   * second tap on the same pin. */
  focusKey?: string
  /** Where focus goes back to on close. Map markers don't take focus on a tap, so the page names the pin. */
  returnFocus?: () => Element | null | undefined
}) {
  const root = useRef<HTMLElement>(null)
  const [room, setRoom] = useState(0)
  const [shown, setShown] = useState(false)
  const [closing, setClosing] = useState(false)
  const drag = useRef<{ id: number; y0: number; h0: number; moved: boolean; onHandle: boolean; trail: { y: number; t: number }[] } | null>(null)
  const heightRef = useRef(0)
  const onHeightRef = useRef(onHeight); onHeightRef.current = onHeight
  const onCloseRef = useRef(onClose); onCloseRef.current = onClose
  const snapRef = useRef(snap); snapRef.current = snap
  const returnRef = useRef(returnFocus); returnRef.current = returnFocus

  const heights = useCallback((): Record<Snap, number> => {
    const full = Math.max(PEEK + 80, Math.round(room * .9))
    return { peek: Math.min(PEEK, full), half: Math.min(full, Math.max(PEEK + 40, Math.round(room * .5))), full }
  }, [room])

  const apply = useCallback((px: number) => {
    heightRef.current = px
    if (root.current) root.current.style.height = `${px}px`
    onHeightRef.current?.(px, snapRef.current)
  }, [])

  // The room to work with is the map stage the sheet sits in.
  useLayoutEffect(() => {
    const parent = root.current?.parentElement
    if (!parent) return
    const measure = () => setRoom(parent.clientHeight)
    measure()
    const watch = new ResizeObserver(measure)
    watch.observe(parent)
    return () => watch.disconnect()
  }, [])

  // Open from zero on the next frame, so the height has something to move from.
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true))
    return () => cancelAnimationFrame(id)
  }, [])
  useLayoutEffect(() => {
    if (!room || drag.current) return
    apply(closing || !shown ? 0 : heights()[snap])
  }, [room, snap, shown, closing, heights, apply])
  useEffect(() => () => onHeightRef.current?.(0, snapRef.current), [])

  const closeTimer = useRef(0)
  const requestClose = useCallback(() => {
    if (closing) return
    setClosing(true)
    closeTimer.current = window.setTimeout(() => onCloseRef.current(), EXIT_MS)
  }, [closing])
  useEffect(() => () => window.clearTimeout(closeTimer.current), [])

  // Focus moves into the sheet on open and whenever the subject changes, and goes
  // back on close. `before` is read during the first render, before any effect here
  // has moved focus.
  const before = useRef<Element | null>(null)
  if (before.current === null) before.current = document.activeElement
  useEffect(() => () => {
    const back = (returnRef.current?.() ?? before.current) as HTMLElement | null
    const here = document.activeElement
    // Only hand focus back if it is still ours to give: in the sheet, or dropped on the page.
    if (back?.isConnected && back !== document.body && (!here || here === document.body || root.current?.contains(here))) back.focus({ preventScroll: true })
  }, [])
  useEffect(() => {
    // A new subject arriving mid-close (another pin tapped) cancels the close, and
    // starts at its top rather than wherever the last one was scrolled to.
    window.clearTimeout(closeTimer.current); setClosing(false)
    root.current?.querySelector('.bsheet-body')?.scrollTo({ top: 0 })
    root.current?.focus({ preventScroll: true })
  }, [focusKey])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (document.querySelector('.ov[role="dialog"]')) return
      const field = document.activeElement
      if (field instanceof HTMLElement && field.matches('input, textarea, select') && root.current?.contains(field)) {
        e.preventDefault(); field.blur(); root.current?.focus({ preventScroll: true })
        return
      }
      e.preventDefault(); requestClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [requestClose])

  function step(dir: 1 | -1) {
    const next = ORDER[ORDER.indexOf(snap) + dir]
    if (next) onSnap(next)
    else if (dir < 0) requestClose()
  }

  function down(e: React.PointerEvent) {
    // Buttons in the title row (close) keep their own tap.
    if ((e.target as HTMLElement).closest('button:not(.bsheet-handle), a, input, label')) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    // Noted now: once the row captures the pointer, the lift lands on the row, not the handle.
    const onHandle = !!(e.target as HTMLElement).closest('.bsheet-handle')
    drag.current = { id: e.pointerId, y0: e.clientY, h0: heightRef.current, moved: false, onHandle, trail: [{ y: e.clientY, t: e.timeStamp }] }
    root.current?.setAttribute('data-dragging', 'true')
  }
  function move(e: React.PointerEvent) {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    if (Math.abs(e.clientY - d.y0) > 6) d.moved = true
    // The last tenth of a second of movement is what a flick is.
    d.trail.push({ y: e.clientY, t: e.timeStamp })
    while (d.trail.length > 2 && e.timeStamp - d.trail[0].t > 100) d.trail.shift()
    const h = heights()
    apply(Math.max(40, Math.min(h.full, d.h0 - (e.clientY - d.y0))))
  }
  function up(e: React.PointerEvent) {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    drag.current = null
    root.current?.removeAttribute('data-dragging')
    const h = heights()
    if (!d.moved) {
      // A tap on the handle steps up, and from the top back down to half.
      if (d.onHandle && e.type === 'pointerup') onSnap(snap === 'full' ? 'half' : ORDER[ORDER.indexOf(snap) + 1])
      apply(h[snap])
      return
    }
    const now = heightRef.current
    const first = d.trail[0], last = d.trail[d.trail.length - 1]
    const velocity = (first.y - last.y) / Math.max(16, last.t - first.t) // px/ms, up is positive
    if (now < h.peek - 36 || (velocity < -.6 && snap === 'peek')) { requestClose(); return }
    let target: Snap
    if (velocity > .5) target = ORDER.find(s => h[s] > now + 8) ?? 'full'
    else if (velocity < -.5) target = [...ORDER].reverse().find(s => h[s] < now - 8) ?? 'peek'
    else target = ORDER.reduce((best, s) => Math.abs(h[s] - now) < Math.abs(h[best] - now) ? s : best, 'peek' as Snap)
    onSnap(target)
    apply(h[target])
  }

  return <section ref={root} className="bsheet" role="dialog" aria-modal="false" aria-label={label} tabIndex={-1} data-snap={snap} data-closing={closing || undefined}>
    <div className="bsheet-top" onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}>
      <button type="button" className="bsheet-handle" aria-label={snap === 'full' ? t('sheet.smaller') : t('sheet.bigger')}
        onKeyDown={e => { if (e.key === 'ArrowUp') { e.preventDefault(); step(1) } if (e.key === 'ArrowDown') { e.preventDefault(); step(-1) } }}
        onClick={e => { if (e.detail === 0) onSnap(snap === 'full' ? 'half' : ORDER[ORDER.indexOf(snap) + 1]) }}><span /></button>
      <div className="bsheet-head">
        <div className="bsheet-title">{header}</div>
        <button type="button" className="bsheet-close" aria-label={t('common.close')} onClick={requestClose}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>
    </div>
    <div className="bsheet-body">{children}</div>
  </section>
}
