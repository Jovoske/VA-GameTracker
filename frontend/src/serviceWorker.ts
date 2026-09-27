import { useSyncExternalStore } from 'react'

/**
 * The service worker, and whether a newer build has taken over from it.
 *
 * An installed app can stay open for days. Each deploy installs a new worker
 * (sw.js carries the build id), which stores the new build and tells every open
 * page its id. A page running an older build then offers "Reload" instead of
 * quietly running old code until the phone happens to restart it (audit D-18).
 */
let newerBuild = false
const listeners = new Set<() => void>()
const UPDATE_EVERY_MS = 30 * 60_000

export function registerServiceWorker(): void {
  // The dev server has no build to store; a worker there only gets in the way.
  if (!import.meta.env.PROD || !('serviceWorker' in navigator)) return
  const sw = navigator.serviceWorker
  sw.addEventListener('message', (e) => {
    const msg = e.data as { type?: string; build?: string } | null
    if (msg?.type !== 'gs-sw-build' || !msg.build || msg.build === __GS_BUILD__ || newerBuild) return
    newerBuild = true
    listeners.forEach((f) => f())
  })
  sw.startMessages()
  window.addEventListener('load', () => {
    sw.register('/sw.js')
      .then((reg) => {
        // Browsers look for a new sw.js when a page opens; an app brought back to the
        // front from the background doesn't open a page, so ask then too.
        let last = Date.now()
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState !== 'visible' || Date.now() - last < UPDATE_EVERY_MS) return
          last = Date.now()
          reg.update().catch(() => {})
        })
      })
      .catch(() => {})
  })
}

function subscribe(f: () => void) {
  listeners.add(f)
  return () => { listeners.delete(f) }
}

/** True once a newer build of the app is stored on the phone and waiting for a reload. */
export function useNewerBuild(): boolean {
  return useSyncExternalStore(subscribe, () => newerBuild)
}
