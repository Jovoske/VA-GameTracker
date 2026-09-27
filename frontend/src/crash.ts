import { getToken } from './api'

/**
 * What broke on this phone, sent to the owner.
 *
 * A black screen in a valley used to leave no trace: the hunter killed the app,
 * opened it again and maybe mentioned it a week later (audit K-14). Every uncaught
 * error, unhandled promise and page crash is now posted to /api/client-errors with
 * the page and the build, and admins read the last few in Settings. With no signal
 * the report waits on the phone and goes when signal is back.
 *
 * Kept small on purpose: a handful per page load, each message once, so a phone
 * stuck in a loop is a few lines and not a flood.
 */

export type CrashKind = 'error' | 'rejection' | 'render' | 'chunk'
type Report = { kind: CrashKind; message: string; stack: string | null; route: string; build: string }

const OUTBOX = 'gs_crash_outbox'
const OUTBOX_MAX = 10
const PER_LOAD = 5
let sent = 0
const seen = new Set<string>()

/** Noise that isn't a fault in the app: an observer that skipped a frame, another
 *  site's script, a request this app gave up on itself, a phone with no signal. */
function ignorable(message: string, err: unknown): boolean {
  const x = err as { name?: string; offline?: boolean; timeout?: boolean; status?: number; stack?: string }
  if (x?.name === 'AbortError' || x?.offline || x?.timeout) return true
  // A refusal (4xx) is an answer and a dead server (5xx) is the server's own log's
  // business, not a crash on the phone; so is being signed out.
  if (x?.status && x.status >= 400) return true
  if (/ResizeObserver loop|^Script error\.?$|^You were signed out/i.test(message)) return true
  return /chrome-extension:|moz-extension:|safari-extension:/.test(x?.stack ?? '')
}

/** A file of the app that didn't arrive: a deploy deleted it, or it never reached the phone. */
export function isChunkError(err: unknown): boolean {
  const x = err as { name?: string; message?: string }
  return (
    x?.name === 'ChunkLoadError' ||
    /dynamically imported module|Importing a module script failed|Unable to preload CSS|error loading dynamically imported|Expected a JavaScript/i.test(
      String(x?.message ?? err),
    )
  )
}

export function reportCrash(kind: CrashKind, err: unknown, stack?: string): void {
  const e = err as { message?: unknown; stack?: unknown } | null
  const message = String((e && e.message) || err || 'Unknown error').slice(0, 500)
  if (ignorable(message, err)) return
  const key = `${kind}|${message}`
  if (seen.has(key) || sent >= PER_LOAD) return
  seen.add(key)
  sent += 1
  const trace = stack ?? (typeof e?.stack === 'string' ? e.stack : '')
  send({ kind, message, stack: trace.slice(0, 4000) || null, route: location.pathname, build: __GS_BUILD__ })
}

function send(report: Report): void {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  fetch('/api/client-errors', { method: 'POST', headers, body: JSON.stringify(report), keepalive: true })
    .then((r) => { if (r.status >= 500) keep(report) })
    .catch(() => keep(report))
}

function keep(report: Report): void {
  try {
    const box = JSON.parse(localStorage.getItem(OUTBOX) || '[]') as Report[]
    box.push(report)
    localStorage.setItem(OUTBOX, JSON.stringify(box.slice(-OUTBOX_MAX)))
  } catch {
    // Storage full or blocked: the report is lost, the app carries on.
  }
}

/** Send what waited on the phone for signal. */
function flushOutbox(): void {
  let box: Report[] = []
  try {
    box = JSON.parse(localStorage.getItem(OUTBOX) || '[]')
    localStorage.removeItem(OUTBOX)
  } catch {
    return
  }
  box.forEach(send)
}

const RELOAD_KEY = 'gs_reloaded_at'
let reloading = false
let pending: Promise<ReloadResult> | null = null

/** A reload for the app's own files is on its way: nothing to show or report. */
export const isReloading = () => reloading

/** What came of asking for a reload: done, refused because one was just tried, or
 *  refused because the server can't be reached (the phone has no signal). */
export type ReloadResult = 'reloading' | 'recent' | 'no-signal'

/**
 * Reload once to pick up the files of the build the server has now.
 *
 * Refused within a minute of the last one (sessionStorage), so a file that is truly
 * missing ends on a message with a Reload button instead of a loop. Refused, too,
 * when the server doesn't answer: a reload with no signal is the browser's own
 * offline page, which is worse than the message. /api/health is never answered by
 * the service worker, so it is a real test of the link.
 */
export function reloadOnce(): Promise<ReloadResult> {
  if (pending) return pending
  const attempt = (async (): Promise<ReloadResult> => {
    try {
      if (Date.now() - Number(sessionStorage.getItem(RELOAD_KEY) || 0) < 60_000) return 'recent'
    } catch {
      return 'recent' // no guard, no reload: a loop is worse than a message
    }
    if (navigator.onLine === false) return 'no-signal'
    const ctl = new AbortController()
    const timer = window.setTimeout(() => ctl.abort(), 5000)
    try {
      const r = await fetch('/api/health', { cache: 'no-store', signal: ctl.signal })
      if (!r.ok) return 'no-signal'
    } catch {
      return 'no-signal'
    } finally {
      window.clearTimeout(timer)
    }
    try {
      sessionStorage.setItem(RELOAD_KEY, String(Date.now()))
    } catch {
      return 'recent'
    }
    reloading = true
    location.reload()
    return 'reloading'
  })()
  pending = attempt
  // Refused: a later failure (signal back, another tap on Map) may try again.
  attempt.then((r) => { if (r !== 'reloading' && pending === attempt) pending = null })
  return attempt
}

export function installCrashReporting(): void {
  window.addEventListener('error', (ev) => {
    if (isChunkError(ev.error ?? ev.message)) return // the page boundary deals with these
    reportCrash('error', ev.error ?? ev.message)
  })
  window.addEventListener('unhandledrejection', (ev) => {
    if (isChunkError(ev.reason)) return
    reportCrash('rejection', ev.reason)
  })
  // Vite's own signal that a lazily loaded file failed (the map, after a deploy
  // deleted it). The failure still goes on to the page boundary, which says so
  // while this finds out whether a reload can get the new build.
  window.addEventListener('vite:preloadError', (ev) => {
    const payload = (ev as Event & { payload?: unknown }).payload
    reportCrash('chunk', payload)
    reloadOnce()
  })
  window.addEventListener('online', flushOutbox)
  flushOutbox()
}
