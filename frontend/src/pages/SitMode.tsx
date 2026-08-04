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

export default function SitMode() {
  const { sitId } = useParams()
  const nav = useNavigate()
  const [sit, setSit] = useState<Sit | null>(null)
  const [clock, setClock] = useState(new Date())
  const [pending, setPending] = useState(0)
  const [flash, setFlash] = useState('')
  const holdTimer = useRef<number | null>(null)

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
      try {
        lock?.release()
      } catch {
        /* already gone */
      }
    }
  }, [sitId])

  async function record(outcome: string, message: string) {
    if (!sitId) return
    setFlash(message)
    if (navigator.vibrate) navigator.vibrate(20)
    try {
      await api(`/sits/${sitId}`, { method: 'PATCH', body: JSON.stringify({ outcome }) })
    } catch {
      queueWrite(sitId, outcome)
      setPending((n) => n + 1)
    }
    setTimeout(() => setFlash(''), 2500)
  }

  function startHold() {
    holdTimer.current = window.setTimeout(() => record('nothing', 'Nothing — logged'), 1200)
  }
  function cancelHold() {
    if (holdTimer.current) window.clearTimeout(holdTimer.current)
    holdTimer.current = null
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
        {pending > 0 && (
          <div style={{ fontSize: 12, opacity: 0.85 }}>
            {pending} entr{pending === 1 ? 'y' : 'ies'} waiting for signal
          </div>
        )}
        {flash && <div style={{ fontSize: 14, marginTop: 4 }}>{flash}</div>}
      </div>

      {/* The whole screen below the header is the button. */}
      <button
        onClick={() => record('seen', 'Seen — logged')}
        onPointerDown={startHold}
        onPointerUp={cancelHold}
        onPointerLeave={cancelHold}
        style={{
          flex: 1,
          background: 'transparent',
          border: 'none',
          color: AMBER,
          fontSize: 30,
          fontWeight: 700,
          letterSpacing: '.06em',
          cursor: 'pointer',
        }}
      >
        TAP = SEEN
        <div style={{ fontSize: 15, fontWeight: 400, marginTop: 14, opacity: 0.8 }}>
          hold = nothing yet
        </div>
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
