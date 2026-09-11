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
const stack: symbol[] = []
// Each open panel is also one entry in the browser history, so the phone's Back
// gesture closes the panel instead of leaving the page it opened over — which
// is what it did, and after paging through twenty photos it read as the app
// throwing you out. Ids only ever go up: a popstate whose id is below mine
// means my entry is gone. A reload lands on whatever entry was current, panel
// id and all, so the count starts above it rather than at zero.
let seq = (window.history.state?.ov as number | undefined) || 0

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
  children,
}: {
  onClose: () => void
  backdrop?: string
  zIndex?: number
  style?: CSSProperties
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const closing = useRef(false)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose
  const me = useRef(Symbol('overlay'))
  const hist = useRef(0)

  useEffect(() => {
    const release = lockScroll()
    const id_ = me.current
    stack.push(id_)
    // Same URL, one more entry. react-router's own state rides along so a reload
    // on this entry still lands on the right page. StrictMode runs this twice in
    // dev, so an entry this instance already pushed is reused, not doubled.
    if (!hist.current || window.history.state?.ov !== hist.current) {
      hist.current = ++seq
      window.history.pushState({ ...(window.history.state ?? {}), ov: hist.current }, '')
    }
    const hid = hist.current
    const onPop = () => {
      const cur = (window.history.state?.ov as number | undefined) ?? 0
      if (cur >= hid) return // still at (or ahead of) my entry: a Forward, not a Back
      close()
    }
    window.addEventListener('popstate', onPop)
    // Flip on the next frame so the transition has two states to move between.
    const id = requestAnimationFrame(() => setOpen(true))
    return () => {
      cancelAnimationFrame(id)
      window.removeEventListener('popstate', onPop)
      const i = stack.indexOf(id_)
      if (i >= 0) stack.splice(i, 1)
      release()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function close() {
    if (closing.current) return
    closing.current = true
    setOpen(false)
    // Closed from inside (button, Escape, backdrop): drop my history entry too, so
    // the next Back goes where it would have before this panel opened. When Back
    // itself did the closing the entry is already gone.
    if ((window.history.state?.ov as number | undefined) === hist.current) window.history.back()
    window.setTimeout(() => onCloseRef.current(), EXIT_MS)
  }

  // Escape closes, on every overlay rather than just the one that remembered to,
  // and only on the topmost one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (stack[stack.length - 1] !== me.current) return
      close()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div
      className="ov"
      data-open={open}
      onClick={close}
      style={{ background: backdrop, zIndex, ...style }}
    >
      {children(close)}
    </div>
  )
}
