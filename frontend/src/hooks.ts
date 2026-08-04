import { useEffect, useRef } from 'react'

/**
 * Re-run `fn` when the user comes back to the app (tab visible / window focused),
 * at most once per `minIntervalMs`. Keeps a phone that's been asleep from showing
 * stale data without hammering the API on every focus flicker.
 */
export function useRefetchOnReturn(fn: () => void, minIntervalMs = 60_000) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  const last = useRef(Date.now())

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
