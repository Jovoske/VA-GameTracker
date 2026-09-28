import { useEffect, useRef, useState } from 'react'
import { onServerLanguage } from './api'

/**
 * Re-run `fn` when the user comes back to the app (tab visible / window focused),
 * at most once per `minIntervalMs`. Keeps a phone that's been asleep from showing
 * stale data without hammering the API on every focus flicker.
 *
 * And at once when a language chosen on this phone reaches the server: what the
 * page holds from it (the plan's lines, reasons, animal names) was written in the
 * old one (useOnServerLanguage).
 */
export function useRefetchOnReturn(fn: () => void, minIntervalMs = 60_000) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  const last = useRef(Date.now())

  useOnServerLanguage(() => {
    last.current = Date.now()
    fnRef.current()
  })

  useEffect(() => {
    const maybe = () => {
      if (document.visibilityState !== 'visible') return
      if (Date.now() - last.current < minIntervalMs) return
      last.current = Date.now()
      fnRef.current()
    }
    document.addEventListener('visibilitychange', maybe)
    window.addEventListener('focus', maybe)
    return () => {
      document.removeEventListener('visibilitychange', maybe)
      window.removeEventListener('focus', maybe)
    }
  }, [minIntervalMs])
}

/**
 * Run `fn` when the server starts answering this person in another language (a
 * choice made on this phone reached it), for a page whose words from the server
 * should follow: signed in with Suomi picked on the sign-in page, Tonight's lines
 * came in the person's old language until then (api.ts onServerLanguage).
 */
export function useOnServerLanguage(fn: () => void) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => onServerLanguage(() => fnRef.current()), [])
}

/**
 * False on the paint where `ready` first turns true, true one frame later.
 *
 * The two-state handshake a CSS transition needs in order to have something to
 * move between. `@starting-style` does this in the stylesheet, but not on every
 * iOS version this PWA gets installed on, so it happens here instead.
 *
 * Pass the thing being waited for. Every page here returns early until its data
 * lands, so a flag tied to component mount would already be true by the time
 * the charts exist and nothing would ever animate. Latches on: this is an
 * arrival, not a state the UI keeps toggling.
 */
export function useReveal(ready = true): boolean {
  const [on, setOn] = useState(false)
  useEffect(() => {
    if (!ready || on) return
    const id = requestAnimationFrame(() => setOn(true))
    return () => cancelAnimationFrame(id)
  }, [ready, on])
  return on
}

/**
 * Whether the user has asked their phone to calm down.
 *
 * Only needed where motion is driven from JS and CSS cannot see it — the wind
 * arrowhead on the map. Everything else branches in theme.css.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  )
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mq) return
    const on = () => setReduced(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduced
}
