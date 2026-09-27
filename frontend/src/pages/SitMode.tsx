import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { type Got, ageLabel, fromEarlierNight, getFresh, nightOf, peek } from '../api'
import { isCall, type MapData } from '../map/geometry'
import { flushSits, onSitSync, pendingFor, rank, saveSit } from '../sits'

/**
 * Sit Mode: the screen that works in a high seat at midnight.
 *
 *  - True black on OLED, amber only. Green and red are unreadable under a red
 *    headlamp, so colour never carries meaning here.
 *  - Big controls. Cold hands, gloves, one hand already busy.
 *  - No imagery. Nothing to load, nothing to light up the seat.
 *  - Every tap goes onto the phone first and out when there's signal (sits.ts).
 *    The valley has no signal, and a later tap never undoes a better report.
 */

type Sit = {
  id: string
  stand_id: string
  stand: string | null
  outcome: string
  started_at: string | null
  ended_at: string | null
  wind_status: string | null
  wind_text: string | null
  claimed_at?: string | null
  // The moment the saved verdict was judged for (the sit time when it was reserved).
  wind_at?: string | null
  night?: string
  // The sit's own sunset and the sunrise after it: shown with no signal too.
  sunset_local?: string | null
  sunrise_local?: string | null
}

// Tonight's verdict for the stand, from the same place the map and Stands take it,
// for the sit time: 45 min after sunset, or now once that has passed. A dawn sit
// still on after 06:00 is judged for now.
type StandWind = {
  status: string; text: string; at_local?: string; now?: boolean
  sunset_local?: string | null; sunrise_local?: string | null
}

// Short wind headline. The sentence goes underneath.
const WIND_HEAD: Record<string, string> = {
  clean: 'Wind is right',
  scent_carries: 'Wind is wrong',
  too_light: 'Wind too light to call',
  no_wind_data: 'No wind forecast',
  no_geometry: 'Wind not set up for this stand',
  no_bedding: 'No bedding drawn',
  no_position: 'Stand not on the map',
}

// Wind is asked for again this often while the seat is open.
const WIND_EVERY_MS = 15 * 60_000

// The estate's clock, whatever the phone's is set to: Tonight's hours are Spain time.
const estateClock = (d: Date | string) =>
  new Date(d).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' })
// The estate's calendar day, "2026-09-28", to tell a sit's evening from the morning after.
const estateDay = (d: Date) => {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Madrid', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(d).map((x) => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}`
}

// What the flash says is still on record when a lower tap changes nothing.
const KEPT: Record<string, string> = {
  nothing: 'nothing so far',
  seen: 'saw animals',
  shootable_no_shot: 'had a chance, no shot',
  shot: 'shot',
}

// END SIT waits this long for the server, then goes anyway. The end is on the
// phone and goes out with the next signal; nobody should stand in the dark
// watching a button.
const END_WAIT_MS = 4000

const AMBER = '#FFB000'

// Long enough that a knock against the seat rail cannot trigger it, short enough
// that you are not holding a phone up in the cold wondering if it heard you.
const HOLD_MS = 1200

const footButton: React.CSSProperties = {
  flex: 1,
  minHeight: 64,
  background: 'transparent',
  border: 'none',
  color: AMBER,
  fontSize: 15,
  letterSpacing: '.05em',
  cursor: 'pointer',
}

/** This stand's wind and tonight's sunset from /map/tonight as Stands keeps it in
 *  memory, if the phone has it. */
function fromMap(standId: string): Got<StandWind> | null {
  const got = peek<MapData>('/map/tonight')
  const wind = got?.data?.stands?.find((s) => s.id === standId)?.wind
  return got && wind ? { ...got, data: { ...wind, sunset_local: got.data.conditions?.sunset_local } } : null
}

const newest = <T,>(a: Got<T> | null, b: Got<T> | null) =>
  !a ? b : !b ? a : Date.parse(b.at) > Date.parse(a.at) ? b : a

/** This sit as the phone saved it (Stands keeps /sits, Tonight the sit you're on),
 *  to paint before asking. */
const savedSit = (sitId: string | undefined) =>
  peek<Sit[]>('/sits')?.data.find((s) => s.id === sitId) ??
  peek<{ live: Sit[] }>('/sits/mine')?.data.live?.find((s) => s.id === sitId) ??
  null

export default function SitMode() {
  const { sitId } = useParams()
  const nav = useNavigate()
  const [sit, setSit] = useState<Sit | null>(() => savedSit(sitId))
  const [clock, setClock] = useState(new Date())
  // A report for this sit is on the phone and a send found no signal. Read from
  // the phone, so it survives a reload or the app being killed (audit A-25).
  const [pending, setPending] = useState(() => !!(sitId && pendingFor(sitId)?.waiting))
  const [ending, setEnding] = useState(false)
  const [flash, setFlash] = useState('')
  const [holding, setHolding] = useState(false)
  const holdTimer = useRef<number | null>(null)
  const flashTimer = useRef<number | null>(null)
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  // The best report so far, from the server, the phone and this visit's taps.
  const best = useRef<string | undefined>(undefined)
  // A completed hold has already recorded "nothing". Lifting your finger then
  // fires the button's click, which must not record "seen" over the top of it.
  const holdFired = useRef(false)

  function say(message: string, ms = 2500) {
    setFlash(message)
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash(''), ms)
  }
  const know = (s: Sit | null) => {
    if (s && rank(s.outcome) > rank(best.current)) best.current = s.outcome
  }

  useEffect(() => {
    // The copy saved on the phone paints first, so the stand and the wind it was
    // reserved on show in the seat at once, with no signal too; the network then
    // replaces it. Nothing saved and no answer: the seat still works, unnamed.
    const saved = savedSit(sitId)
    setSit(saved)
    best.current = sitId ? pendingFor(sitId)?.outcome : undefined
    know(saved)
    const ctl = new AbortController()
    getFresh<Sit[]>('/sits', { save: true, timeoutMs: 20_000, signal: ctl.signal })
      .then((got) => {
        const s = got.data.find((x) => x.id === sitId) ?? null
        setSit((had) => s ?? had)
        know(s)
      })
      .catch(() => {})
    const t = setInterval(() => setClock(new Date()), 1000)
    return () => {
      ctl.abort()
      clearInterval(t)
      if (flashTimer.current) window.clearTimeout(flashTimer.current)
    }
  }, [sitId])

  // Tonight's wind for this stand, asked again every quarter hour, so the seat says
  // what the map says now rather than what it said at the reservation. The copy the
  // phone has shows with no signal, with its age; one from an earlier night never does.
  // Asked with the sit: a dawn sit still on after 06:00 is judged for now, not for
  // the coming evening.
  const standId = sit?.stand_id
  const pastNight = !!sit?.night && sit.night < nightOf(Date.now())
  const [live, setLive] = useState<Got<StandWind> | null>(null)
  useEffect(() => {
    if (!standId || !sitId) return
    const path = `/stands/${standId}/wind?sit=${sitId}`
    // What Stands just loaded for this stand paints first: the same verdict. Not for a
    // dawn sit after 06:00: that copy is for the coming evening.
    const had = newest(peek<StandWind>(path), pastNight ? null : fromMap(standId))
    setLive(had && !fromEarlierNight(had.at) ? had : null)
    let ctl = new AbortController()
    const ask = () => {
      ctl.abort()
      ctl = new AbortController()
      getFresh<StandWind>(path, { save: true, timeoutMs: 20_000, signal: ctl.signal })
        .then((got) => { if (!fromEarlierNight(got.at)) setLive(got) })
        .catch(() => {})
    }
    ask()
    const t = window.setInterval(() => { if (document.visibilityState === 'visible') ask() }, WIND_EVERY_MS)
    return () => {
      ctl.abort()
      window.clearInterval(t)
    }
  }, [standId, sitId, pastNight])

  // Keep the screen on: a sit is hours long and re-waking a phone in the dark
  // with gloves on is exactly the friction this screen exists to remove. The
  // phone drops the lock whenever the app goes to the back (a glance at a
  // message, the power button), so take it again each time Sit mode comes back
  // to the front (audit A-17, I-23, J-15).
  useEffect(() => {
    type Lock = { release: () => Promise<void> }
    const wake = (navigator as Navigator & { wakeLock?: { request: (t: 'screen') => Promise<Lock> } }).wakeLock
    let lock: Lock | null = null
    let gone = false
    const take = () => {
      if (!wake || document.visibilityState !== 'visible') return
      wake.request('screen').then((l) => {
        // Left Sit mode while the request was out: let it go at once, don't leak it.
        if (gone) return void l.release().catch(() => {})
        const old = lock
        lock = l
        old?.release().catch(() => {})
      }).catch(() => {})
    }
    take()
    document.addEventListener('visibilitychange', take)
    return () => {
      gone = true
      document.removeEventListener('visibilitychange', take)
      lock?.release().catch(() => {})
    }
  }, [])

  // Anything left on the phone from before (a reload, the app killed) goes now;
  // sits.ts keeps trying while it waits. Say so when signal comes back.
  useEffect(() => {
    if (!sitId) return
    const off = onSitSync((r) => {
      const left = pendingFor(sitId)
      if (pendingRef.current && !left && r.sent > 0) say(r.reports > 0 ? 'Signal’s back. Report sent.' : 'Signal’s back.', 3500)
      setPending(!!left?.waiting)
    })
    void flushSits()
    return off
  }, [sitId])

  function record(outcome: string, message: string) {
    if (!sitId) return
    if (navigator.vibrate) navigator.vibrate(20)
    // A lower tap changes nothing. Say what's still on record rather than
    // "Saved: saw animals" over a shot.
    const kept = best.current
    if (kept && rank(outcome) < rank(kept)) say(`Still saved: ${KEPT[kept] ?? kept}`)
    else {
      best.current = outcome
      say(message)
    }
    saveSit(sitId, { outcome })
      .then((r) => setPending(r === 'queued'))
      .catch((e: Error) => say(`Not saved. ${e.message}`, 5000))
  }

  async function endSit() {
    if (!sitId || ending) return
    setEnding(true)
    await Promise.race([
      saveSit(sitId, { end: true }).catch(() => {}),
      new Promise((done) => window.setTimeout(done, END_WAIT_MS)),
    ])
    // Straight to this stand on Stands, which asks what happened if nothing was said.
    nav(sit?.stand_id ? `/stands?stand=${sit.stand_id}` : '/stands')
  }

  function startHold() {
    holdFired.current = false
    setHolding(true)
    holdTimer.current = window.setTimeout(() => {
      holdFired.current = true
      setHolding(false)
      // Two pulses, because at this point you are not looking at the screen.
      if (navigator.vibrate) navigator.vibrate([25, 60, 25])
      record('nothing', 'Saved: nothing so far')
    }, HOLD_MS)
  }
  function cancelHold() {
    if (holdTimer.current) window.clearTimeout(holdTimer.current)
    holdTimer.current = null
    setHolding(false)
  }
  function onTap() {
    // Swallow the click that follows a hold that already did its job.
    if (holdFired.current) {
      holdFired.current = false
      return
    }
    record('seen', 'Saved: saw animals')
  }

  // The live verdict when the phone has one from tonight; else the one saved when the
  // stand was reserved, said as such.
  const wind = live?.data ?? null
  const windHead = wind ? WIND_HEAD[wind.status] : sit?.wind_status ? WIND_HEAD[sit.wind_status] : null
  const windText = wind ? wind.text : sit?.wind_text
  // Only a call has a time: "Not on the map yet" is not a verdict for 20:39.
  const windWhen = wind
    ? [isCall(wind.status) && (wind.now ? 'now' : wind.at_local && `for ${wind.at_local}`),
      live?.stale && `checked ${ageLabel(live.at)}`].filter(Boolean).join(', ') || null
    : sit?.wind_text
      ? `when you reserved${sit.claimed_at ? ` at ${estateClock(sit.claimed_at)}` : ''}${sit.wind_at && isCall(sit.wind_status) ? `, for ${estateClock(sit.wind_at)}` : ''}`
      : null
  // Sunset from the live answer, or the sit's own when there is none; once the sit's
  // night is past midnight, the sunrise that ends it.
  const sunset = wind?.sunset_local ?? sit?.sunset_local
  const sunrise = wind?.sunrise_local ?? sit?.sunrise_local
  const pastMidnight = sit?.night ? estateDay(clock) > sit.night : Number(estateClock(clock).slice(0, 2)) < 12
  const sun = pastMidnight && sunrise ? `Sunrise ${sunrise}` : sunset ? `Sunset ${sunset}` : null

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#000',
        color: AMBER,
        display: 'flex',
        flexDirection: 'column',
        zIndex: 100,
        userSelect: 'none',
        WebkitUserSelect: 'none',
      }}
    >
      <div style={{ padding: '16px 18px', borderBottom: `1px solid ${AMBER}33` }}>
        <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em' }}>
          {sit?.stand ?? 'Your sit'}
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <span style={{ fontSize: 34, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
            {estateClock(clock)}
          </span>
          {sun && (
            <span style={{ fontSize: 15, opacity: 0.85, fontVariantNumeric: 'tabular-nums' }}>
              {sun}
            </span>
          )}
        </div>
        {(windHead || windText) && (
          <div style={{ marginTop: 6, fontSize: 14, lineHeight: 1.4 }}>
            {windHead && (
              <div style={{ fontWeight: 600 }}>
                {windHead}
                {windWhen && <span style={{ fontWeight: 400, opacity: 0.8 }}> · {windWhen}</span>}
              </div>
            )}
            {windText && <div style={{ opacity: 0.8 }}>{windText}</div>}
          </div>
        )}
        {/* Both lines keep their space whether or not they have anything to say.
            They sit directly above the button, and a line appearing would shove
            the target down the screen as a thumb comes off it. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 10,
            minHeight: 21,
            marginTop: 2,
            fontSize: 14,
          }}
        >
          <span style={{ opacity: flash ? 1 : 0, transition: 'opacity var(--d-fast) var(--ease-out)' }}>
            {flash || ' '}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 12, opacity: pending ? 0.85 : 0 }}>
            {/* Held space, not held text: an invisible line would still be read out. */}
            {pending ? 'Saved on phone, no signal' : ''}
          </span>
        </div>
      </div>

      {/* The whole screen below the header is the button. */}
      <button
        className="no-press"
        onClick={onTap}
        onPointerDown={startHold}
        onPointerUp={cancelHold}
        onPointerLeave={cancelHold}
        onPointerCancel={cancelHold}
        aria-label="Saw animals. Hold to save: saw nothing"
        style={{
          flex: 1,
          position: 'relative',
          overflow: 'hidden',
          background: 'transparent',
          border: 'none',
          color: AMBER,
          fontSize: 30,
          fontWeight: 700,
          letterSpacing: '.06em',
          cursor: 'pointer',
          touchAction: 'none',   /* a hold must not become a scroll */
        }}
      >
        {/* The hold's only evidence. It is a progress readout, not decoration, so
            it stays on under reduced motion. Fills at a constant rate. */}
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            background: `${AMBER}1F`,
            transformOrigin: 'left center',
            transform: holding ? 'scaleX(1)' : 'scaleX(0)',
            transition: holding
              ? `transform ${HOLD_MS}ms linear`
              : 'transform var(--d-fast) var(--ease-out)',
            pointerEvents: 'none',
          }}
        />
        <span style={{ position: 'relative' }}>
          SAW ANIMALS
          <span style={{ display: 'block', fontSize: 15, fontWeight: 400, marginTop: 14, opacity: 0.8, letterSpacing: 0 }}>
            Tap. Or hold for “saw nothing”.
          </span>
        </span>
      </button>

      <div style={{ display: 'flex', borderTop: `1px solid ${AMBER}33` }}>
        <button
          onClick={() => record('shot', 'Saved: shot')}
          style={{ ...footButton, borderRight: `1px solid ${AMBER}33` }}
        >
          SHOT
        </button>
        <button onClick={endSit} disabled={ending} aria-busy={ending} style={footButton}>
          {ending ? 'ENDING…' : 'END SIT'}
        </button>
      </div>
    </div>
  )
}
