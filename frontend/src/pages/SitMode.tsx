import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'

/**
 * Sit Mode — the one interaction that works in a high seat at midnight.
 *
 * Design constraints come from the physical situation, not from taste:
 *  - True black on OLED, amber only. A non-black background is a lit rectangle in
 *    a dark high seat: it costs battery and concealment. Green/red would be worse
 *    than useless under a red headlamp, where green reads near-black and red reads
 *    white — a colour-coded control there inverts its own meaning.
 *  - Two controls, both enormous. Cold hands, gloves, one hand already occupied.
 *  - No imagery. Nothing to load, nothing to light up the seat.
 *  - Writes queue locally if the tap fails, because the valley has no signal and
 *    losing the outcome loses the only ground truth this app ever gets.
 *
 * This is simultaneously the night-ergonomics feature and the ForecastOutcome
 * write path. They turned out to be the same feature.
 */

const QUEUE_KEY = 'gs_sit_queue'

type Sit = {
  id: string
  stand: string | null
  outcome: string
  started_at: string | null
}

function queueWrite(sitId: string, outcome: string) {
  try {
    const q = JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]')
    q.push({ sitId, outcome, at: new Date().toISOString() })
    localStorage.setItem(QUEUE_KEY, JSON.stringify(q))
  } catch {
    /* nothing more we can do here */
  }
}

export async function flushSitQueue(): Promise<number> {
  let queue: { sitId: string; outcome: string }[] = []
  try {
    queue = JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]')
  } catch {
    return 0
  }
  const left: typeof queue = []
  for (const item of queue) {
    try {
      await api(`/sits/${item.sitId}`, {
        method: 'PATCH',
        body: JSON.stringify({ outcome: item.outcome }),
      })
    } catch {
      left.push(item)
    }
  }
  localStorage.setItem(QUEUE_KEY, JSON.stringify(left))
  return queue.length - left.length
}

const AMBER = '#FFB000'

// Long enough that a knock against the seat rail cannot trigger it, short enough
// that you are not holding a phone up in the cold wondering if it heard you.
const HOLD_MS = 1200

export default function SitMode() {
  const { sitId } = useParams()
  const nav = useNavigate()
  const [sit, setSit] = useState<Sit | null>(null)
  const [clock, setClock] = useState(new Date())
  const [pending, setPending] = useState(0)
  const [flash, setFlash] = useState('')
  const [holding, setHolding] = useState(false)
  const holdTimer = useRef<number | null>(null)
  const flashTimer = useRef<number | null>(null)
  // A completed hold has already recorded "nothing". Lifting your finger then
  // fires the button's click, which used to record "seen" straight over the top
  // of it — so holding logged the opposite of what it says on the button, and
  // the only ground truth this app ever gets was being written wrong.
  const holdFired = useRef(false)

  useEffect(() => {
    api<Sit[]>('/sits')
      .then((all) => setSit(all.find((s) => s.id === sitId) ?? null))
      .catch(() => setSit(null))
    const t = setInterval(() => setClock(new Date()), 1000)

    // Keep the screen on: a sit is hours long and re-waking a phone in the dark
    // with gloves on is exactly the friction this screen exists to remove.
    let lock: { release: () => void } | null = null
    const nav0 = navigator as Navigator & { wakeLock?: { request: (t: string) => Promise<any> } }
    nav0.wakeLock?.request('screen').then((l: any) => (lock = l)).catch(() => {})

    return () => {
      clearInterval(t)
      if (flashTimer.current) window.clearTimeout(flashTimer.current)
      try {
        lock?.release()
      } catch {
        /* already gone */
      }
    }
  }, [sitId])

  // Signal comes back mid-sit more often than not — a shift in the seat is enough.
  // Drain the queue there and then, and say so: the whole reason this screen keeps
  // a local queue is that losing a night's outcomes loses the only ground truth
  // the forecast is ever scored against, and the user deserves to see it land.
  useEffect(() => {
    const onOnline = async () => {
      const n = await flushSitQueue()
      if (n <= 0) return
      setPending((p) => Math.max(0, p - n))
      setFlash(`${n} entr${n === 1 ? 'y' : 'ies'} sent — signal is back`)
      if (flashTimer.current) window.clearTimeout(flashTimer.current)
      flashTimer.current = window.setTimeout(() => setFlash(''), 3500)
    }
    window.addEventListener('online', onOnline)
    return () => window.removeEventListener('online', onOnline)
  }, [])

  async function record(outcome: string, message: string) {
    if (!sitId) return
    setFlash(message)
    if (navigator.vibrate) navigator.vibrate(20)
    if (flashTimer.current) window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash(''), 2500)
    try {
      await api(`/sits/${sitId}`, { method: 'PATCH', body: JSON.stringify({ outcome }) })
    } catch {
      queueWrite(sitId, outcome)
      setPending((n) => n + 1)
    }
  }

  function startHold() {
    holdFired.current = false
    setHolding(true)
    holdTimer.current = window.setTimeout(() => {
      holdFired.current = true
      setHolding(false)
      // Two pulses, because at this point you are not looking at the screen.
      if (navigator.vibrate) navigator.vibrate([25, 60, 25])
      record('nothing', 'Nothing — logged')
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
    record('seen', 'Seen — logged')
  }

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
        <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: '.04em' }}>
          {sit?.stand ?? 'SIT'}
        </div>
        <div style={{ fontSize: 34, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
          {clock.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
        </div>
        {/* Both lines keep their space whether or not they have anything to say.
            They sit directly above the button, and a line appearing used to shove
            the whole target down the screen at the exact moment a thumb was
            coming off it. */}
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
            {flash || ' '}
          </span>
          <span style={{ marginLeft: 'auto', fontSize: 12, opacity: pending > 0 ? 0.85 : 0 }}>
            {/* Held space, not held text: an invisible "0 waiting for signal"
                still gets read out loud. */}
            {pending > 0 ? `${pending} waiting for signal` : ''}
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
        {/* The hold's only evidence. It is a progress readout rather than
            decoration, so it stays on under reduced motion — a 1.2s wait with
            nothing happening is indistinguishable from a control that is broken.
            Fills at a constant rate (linear); lets go fast when you do. */}
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
          TAP = SEEN
          <span style={{ display: 'block', fontSize: 15, fontWeight: 400, marginTop: 14, opacity: 0.8 }}>
            hold = nothing yet
          </span>
        </span>
      </button>

      <button
        onClick={async () => {
          await flushSitQueue()
          nav('/stands')
        }}
        style={{
          minHeight: 64,
          background: 'transparent',
          border: 'none',
          borderTop: `1px solid ${AMBER}33`,
          color: AMBER,
          fontSize: 15,
          letterSpacing: '.05em',
          cursor: 'pointer',
        }}
      >
        END SIT
      </button>
    </div>
  )
}
