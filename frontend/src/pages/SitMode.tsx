import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'

/**
 * Sit Mode: the screen that works in a high seat at midnight.
 *
 *  - True black on OLED, amber only. Green and red are unreadable under a red
 *    headlamp, so colour never carries meaning here.
 *  - Big controls. Cold hands, gloves, one hand already busy.
 *  - No imagery. Nothing to load, nothing to light up the seat.
 *  - Writes queue locally if the tap fails; the valley has no signal.
 */

const QUEUE_KEY = 'gs_sit_queue'

type Sit = {
  id: string
  stand: string | null
  outcome: string
  started_at: string | null
  wind_status: string | null
  wind_text: string | null
}

// Short wind headline. The saved sentence from the reservation goes underneath.
const WIND_HEAD: Record<string, string> = {
  clean: 'Wind is right',
  scent_carries: 'Wind is wrong',
  too_light: 'Wind too light to call',
  no_wind_data: 'No wind forecast',
  no_geometry: 'Wind not set up for this stand',
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
  // fires the button's click, which must not record "seen" over the top of it.
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

  // Signal often comes back mid-sit. Drain the queue there and then, and say so.
  useEffect(() => {
    const onOnline = async () => {
      const n = await flushSitQueue()
      if (n <= 0) return
      setPending((p) => Math.max(0, p - n))
      setFlash(`Back online. ${n} report${n === 1 ? '' : 's'} sent.`)
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

  const windHead = sit?.wind_status ? WIND_HEAD[sit.wind_status] : null

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
        <div style={{ fontSize: 34, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
          {clock.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
        </div>
        {(windHead || sit?.wind_text) && (
          <div style={{ marginTop: 6, fontSize: 14, lineHeight: 1.4 }}>
            {windHead && <div style={{ fontWeight: 600 }}>{windHead}</div>}
            {sit?.wind_text && <div style={{ opacity: 0.8 }}>{sit.wind_text}</div>}
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
          <span style={{ marginLeft: 'auto', fontSize: 12, opacity: pending > 0 ? 0.85 : 0 }}>
            {/* Held space, not held text: an invisible "0 saved" would still be read out. */}
            {pending > 0 ? `${pending} saved, no signal` : ''}
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
        <button
          onClick={async () => {
            await flushSitQueue()
            nav('/stands')
          }}
          style={footButton}
        >
          END SIT
        </button>
      </div>
    </div>
  )
}
