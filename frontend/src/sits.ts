import { type Failure, SIT_QUEUE_KEY, api, getToken, tokenSubject } from './api'

/**
 * Sit reports that survive a valley with no signal.
 *
 * The phone keeps ONE entry per sit, not a log of taps: the best report so far and
 * when it was made, and when START and END SIT were tapped. A log replayed in order
 * is how a 20:10 "saw animals" used to land on top of a 20:40 "shot" (audit A-01,
 * I-02, J-02). The server keeps the same rules (a report only goes up; a write
 * older than the one kept is ignored), so a tap can arrive late, twice or out of
 * order and the record stays true.
 *
 * One sender at a time. The 'online' event, coming back to the app, the retry
 * timer, Sit mode, END SIT and Stands all share one flight instead of racing each
 * other (A-02). An entry leaves the phone only after the server took it, and only
 * if nobody tapped again while it was in the air: storage is re-read before every
 * change, never written back from a snapshot.
 */

export type SitChange = { outcome?: string; correct?: boolean; start?: boolean; end?: boolean }

export type PendingSit = {
  sitId: string
  /** Whose report this is (the token's subject). Only they send it. */
  uid: string | null
  outcome?: string
  /** A deliberate "What happened?" answer: the one kind allowed to lower a report. */
  correct?: boolean
  /** When the report was made, by this phone's clock. */
  at?: string
  /** When Sit mode was opened (START). */
  start?: string
  /** When END SIT was tapped. */
  end?: string
}

export type SyncResult = { sent: number; left: number; offline: boolean }

// Up the ladder only; 'unreported' and 'cancelled' sit below it.
export const RANK: Record<string, number> = { nothing: 0, seen: 1, shootable_no_shot: 2, shot: 3 }
export const rank = (outcome: string | undefined) => (outcome && outcome in RANK ? RANK[outcome] : -1)

// A write that hangs is a write with no signal. Long enough for one bar of 3G.
const WRITE_TIMEOUT_MS = 12_000
// While something waits, try again this often (phones rarely say signal is back).
const RETRY_MS = 30_000

function read(): PendingSit[] {
  let raw: unknown
  try {
    raw = JSON.parse(localStorage.getItem(SIT_QUEUE_KEY) || '[]')
  } catch {
    return []
  }
  if (!Array.isArray(raw)) return []
  // Phones updated mid-season still hold the old tap log ({sitId, outcome, at}, many
  // per sit). Fold it into one entry per sit, keeping the best report.
  const bySit = new Map<string, PendingSit>()
  for (const item of raw as PendingSit[]) {
    if (!item || typeof item.sitId !== 'string') continue
    const have = bySit.get(item.sitId)
    if (!have) {
      bySit.set(item.sitId, { ...item, uid: item.uid ?? null })
      continue
    }
    if (item.outcome && (item.correct || rank(item.outcome) > rank(have.outcome))) {
      have.outcome = item.outcome
      have.at = item.at
      have.correct = have.correct || item.correct
    }
    if (item.start && !have.start) have.start = item.start
    if (item.end && !have.end) have.end = item.end
  }
  return [...bySit.values()]
}

function write(queue: PendingSit[]): void {
  try {
    if (queue.length) localStorage.setItem(SIT_QUEUE_KEY, JSON.stringify(queue))
    else localStorage.removeItem(SIT_QUEUE_KEY)
  } catch {
    // Quota or private mode. Nothing more this phone can do.
  }
}

const mine = (entry: PendingSit) => entry.uid == null || entry.uid === tokenSubject()
const empty = (e: PendingSit) => !e.outcome && !e.start && !e.end

/** What this phone still has to send for a sit, if anything. */
export function pendingFor(sitId: string): PendingSit | null {
  return read().find((e) => e.sitId === sitId && mine(e)) ?? null
}

/** How many of this person's sits have something waiting on the phone. */
export function pendingCount(): number {
  return read().filter(mine).length
}

// A sit started and not ended counts as on for this long, as the server says
// (routes_stands.LIVE_FOR): a phone that died before END SIT must not keep it on.
export const LIVE_FOR_MS = 12 * 3600_000

type SitState = { id: string; outcome: string; started_at: string | null; ended_at: string | null }

/** A sit as this phone knows it: the server's copy plus what still waits for signal
 *  (a report, START, END SIT), so ending a sit in the valley doesn't leave the
 *  stand saying "Your sit is on". `unsent` says something is still on the phone. */
export function withPending<S extends SitState>(sit: S): S & { unsent: boolean } {
  const p = pendingFor(sit.id)
  if (!p) return { ...sit, unsent: false }
  const outcome = p.outcome && (p.correct || rank(p.outcome) > rank(sit.outcome)) ? p.outcome : sit.outcome
  return { ...sit, outcome, started_at: sit.started_at ?? p.start ?? null, ended_at: sit.ended_at ?? p.end ?? null, unsent: true }
}

/** Started, not ended, and started recently enough to still be on. */
export function isOn(sit: SitState, now: number = Date.now()): boolean {
  return !!sit.started_at && !sit.ended_at && sit.outcome !== 'cancelled' && now - Date.parse(sit.started_at) < LIVE_FOR_MS
}

/** Signing out takes this person's unsent reports with it (api.signOut): ask first. */
export function confirmSignOut(): boolean {
  const n = pendingCount()
  if (!n) return true
  const what = n === 1 ? 'A sit report hasn’t reached the server yet. Signing out now deletes it' : `${n} sit reports haven’t reached the server yet. Signing out now deletes them`
  return window.confirm(`${what} from this phone. Sign out anyway?`)
}

/** Put a change on the phone. It goes out on the next flush. */
export function queueSit(sitId: string, change: SitChange, now: Date = new Date()): void {
  const queue = read()
  let entry = queue.find((e) => e.sitId === sitId)
  if (!entry) {
    entry = { sitId, uid: tokenSubject() }
    queue.push(entry)
  }
  const at = now.toISOString()
  if (change.outcome) {
    if (change.correct) {
      entry.outcome = change.outcome
      entry.correct = true
      entry.at = at
    } else if (rank(change.outcome) > rank(entry.outcome)) {
      // A lower tap changes nothing: SHOT then a brush of SAW ANIMALS is still SHOT.
      entry.outcome = change.outcome
      entry.at = at
    }
  }
  if (change.start && !entry.start) entry.start = at
  if (change.end && !entry.end) entry.end = at
  write(queue)
}

/** A part the server took: forget it, unless it changed while it was in the air. */
function settle(sitId: string, part: 'outcome' | 'start' | 'end', sent: PendingSit): void {
  const queue = read()
  const entry = queue.find((e) => e.sitId === sitId)
  if (!entry) return
  if (part === 'outcome') {
    if (entry.outcome === sent.outcome && entry.at === sent.at && !!entry.correct === !!sent.correct) {
      delete entry.outcome
      delete entry.at
      delete entry.correct
    }
  } else {
    // START and END are idempotent and the server keeps the first, so a sent one is done.
    delete entry[part]
  }
  write(queue.filter((e) => !empty(e)))
}

function drop(sitId: string): void {
  write(read().filter((e) => e.sitId !== sitId))
}

const writeOpts = (method: string, body: object) => ({ method, body: JSON.stringify(body), timeoutMs: WRITE_TIMEOUT_MS })

/** Start, report, end: in that order, each forgotten as soon as it is through. */
async function send(entry: PendingSit): Promise<void> {
  const id = entry.sitId
  if (entry.start) {
    await api(`/sits/${id}/start`, writeOpts('POST', { at: entry.start }))
    settle(id, 'start', entry)
  }
  if (entry.outcome) {
    await api(`/sits/${id}`, writeOpts('PATCH', { outcome: entry.outcome, at: entry.at, ...(entry.correct ? { correct: true } : {}) }))
    settle(id, 'outcome', entry)
  }
  if (entry.end) {
    await api(`/sits/${id}/end`, writeOpts('POST', { at: entry.end }))
    settle(id, 'end', entry)
  }
}

// A refusal that will never change: the sit is gone, cancelled or not yours. 401
// (sign in again), 408 and 429 are worth another go later; so is anything that
// never got an answer, or a server that is down.
function refusedForGood(e: unknown): boolean {
  const x = e as Failure
  if (x?.offline || x?.timeout || !x?.status) return false
  return x.status >= 400 && x.status < 500 && ![401, 408, 429].includes(x.status)
}

let flight: Promise<SyncResult> | null = null
const listeners = new Set<(r: SyncResult) => void>()
const refused = new Map<string, string>()
const key = (e: PendingSit) => `${e.sitId}|${e.outcome}|${e.at}|${e.correct}|${e.start}|${e.end}`

async function drain(): Promise<SyncResult> {
  let sent = 0
  const tried = new Set<string>()
  // Re-read after every write: a tap can land while one is in the air, and that
  // entry goes next. Bounded, so a finger drumming on the screen can't pin it here.
  for (let turn = 0; turn < 25 && getToken(); turn++) {
    const entry = read().find((e) => mine(e) && !tried.has(key(e)))
    if (!entry) break
    tried.add(key(entry))
    try {
      await send(entry)
      refused.delete(entry.sitId)
      sent++
    } catch (e) {
      if (!refusedForGood(e)) return { sent, left: pendingCount(), offline: true }
      // The server said no for good (cancelled, not yours, gone): keeping it would
      // only say "saved on phone" forever.
      refused.set(entry.sitId, (e as Error).message)
      drop(entry.sitId)
    }
  }
  return { sent, left: pendingCount(), offline: false }
}

/** Send what's waiting. Callers share one flight; nobody starts a second. */
export function flushSits(): Promise<SyncResult> {
  if (!flight) {
    flight = drain()
      .catch(() => ({ sent: 0, left: pendingCount(), offline: true }))
      .then((r) => {
        flight = null
        listeners.forEach((fn) => fn(r))
        return r
      })
  }
  return flight
}

/**
 * Save a change to a sit: onto the phone first, then out if there's signal.
 * Resolves 'queued' when it is waiting for signal. Throws the server's words when
 * the server refused it for good (the entry is dropped).
 */
export async function saveSit(sitId: string, change: SitChange): Promise<'sent' | 'queued'> {
  refused.delete(sitId)
  queueSit(sitId, change)
  let r = await flushSits()
  // The flight we joined may have been finishing when this was queued.
  if (pendingFor(sitId) && !r.offline) r = await flushSits()
  const no = refused.get(sitId)
  if (no) {
    refused.delete(sitId)
    throw new Error(no)
  }
  return pendingFor(sitId) ? 'queued' : 'sent'
}

/** Hear about every finished flush (e.g. "Signal's back. Report sent."). */
export function onSitSync(fn: (r: SyncResult) => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

// Signal often comes back mid-sit, and the phone rarely says so (A-25). Try on the
// 'online' event, whenever the app comes back to the front, and on a timer while
// anything waits.
if (typeof window !== 'undefined') {
  const nudge = () => {
    if (document.visibilityState === 'visible' && pendingCount() > 0) void flushSits()
  }
  window.addEventListener('online', nudge)
  document.addEventListener('visibilitychange', nudge)
  window.setInterval(nudge, RETRY_MS)
}
