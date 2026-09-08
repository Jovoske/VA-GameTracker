import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from 'react'

/**
 * Every full-screen panel in the app: the photo lightbox, the herd-makeup
 * gallery, the species gallery, the bare image zooms.
 *
 * There used to be five copies of this. Only the lightbox handled Escape, none
 * of them stopped the page behind from scrolling — so dismissing a photo on a
 * phone left you somewhere else in the list — and all of them appeared as a hard
 * cut, which reads as the app changing screens rather than as something opening
 * on top of what you were already looking at.
 *
 * Children take a `close` callback so a panel's own Close button runs the exit
 * transition instead of yanking the element out from under it. Anything that
 * should scale in gets `className="ov-panel"`.
 */

// Matches --d-fast in theme.css. The element has to outlive the state that
// opened it for exactly this long.
const EXIT_MS = 150

// Nested overlays are real here — a gallery opens, then a photo zooms on top of
// it — so the scroll lock counts holders rather than toggling a flag, and Escape
// goes to whichever one is actually on top. Every instance listens on `window`,
// so without the stack one Escape would close the photo and the gallery under it
// in the same keystroke.
let locks = 0
let nextOverlay = 0
const stack: symbol[] = []

function lockScroll(): () => void {
  if (locks === 0) {
    document.body.dataset.prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  locks++
  return () => {
    locks = Math.max(0, locks - 1)
    if (locks === 0) {
      document.body.style.overflow = document.body.dataset.prevOverflow ?? ''
      delete document.body.dataset.prevOverflow
    }
  }
}

export default function Overlay({
  onClose,
  backdrop = 'rgba(0, 0, 0, 0.8)',
  zIndex = 50,
  style,
  label = 'Photo gallery',
  backLabel = 'Back to page',
  children,
}: {
  onClose: () => void
  backdrop?: string
  zIndex?: number
  style?: CSSProperties
  label?: string
  backLabel?: string
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const closing = useRef(false)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const me = useRef(Symbol('overlay'))
  const root = useRef<HTMLDivElement>(null)
  const timer = useRef<number>()
  const historyKey = useRef(`overlay-${Date.now()}-${++nextOverlay}`)

  useEffect(() => {
    const release = lockScroll()
    const id_ = me.current
    stack.push(id_)
    if (window.history.state?.gsOverlay !== historyKey.current) {
      window.history.pushState({ ...window.history.state, gsOverlay: historyKey.current }, '')
    }
    // Flip on the next frame so the transition has two states to move between.
    const previousFocus = document.activeElement as HTMLElement | null
    const id = requestAnimationFrame(() => {
      setOpen(true)
      root.current?.querySelector<HTMLButtonElement>('button')?.focus()
    })
    const onPop = () => {
      if (stack[stack.length - 1] === id_ && window.history.state?.gsOverlay !== historyKey.current) dismiss()
    }
    window.addEventListener('popstate', onPop)
    return () => {
      cancelAnimationFrame(id)
      window.clearTimeout(timer.current)
      window.removeEventListener('popstate', onPop)
      const i = stack.indexOf(id_)
      if (i >= 0) stack.splice(i, 1)
      release()
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    }
  }, [])

  function close() {
    if (closing.current) return
    if (window.history.state?.gsOverlay === historyKey.current) window.history.back()
    else dismiss()
  }

  function dismiss() {
    if (closing.current) return
    closing.current = true
    setOpen(false)
    timer.current = window.setTimeout(() => onCloseRef.current(), EXIT_MS)
  }

  // Escape closes, on every overlay rather than just the one that remembered to,
  // and only on the topmost one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== me.current) return
      if (e.key === 'Escape') { e.preventDefault(); close() }
      if (e.key === 'Tab') {
        const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, select, textarea, [tabindex="0"]') ?? [])
          .filter((el) => el.getClientRects().length > 0)
        e.preventDefault()
        const current = controls.indexOf(document.activeElement as HTMLElement)
        const next = current < 0 ? (e.shiftKey ? controls.length - 1 : 0)
          : (current + (e.shiftKey ? -1 : 1) + controls.length) % controls.length
        controls[next]?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      className="ov"
      ref={root}
      role="dialog"
      aria-modal="true"
      aria-label={label}
      data-open={open}
      onClick={(e) => { if (e.target === e.currentTarget) close() }}
      style={{ background: backdrop, zIndex, ...style }}
    >
      <div className="ov-toolbar" onClick={(e) => e.stopPropagation()}>
        <button className="ov-back" onClick={close}>← {backLabel}</button>
        <span>{label}</span>
      </div>
      {children(close)}
    </div>
  )
}
