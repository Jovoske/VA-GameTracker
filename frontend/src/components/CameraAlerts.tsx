import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api'
import SwitchRow from './SwitchRow'

type Failure = Error & { offline?: boolean; timeout?: boolean }
type Saved = { camera_id: string; alerts: boolean; enabled: boolean }

/**
 * One camera's alert switch for the person holding the phone: on, or muted (the busy
 * feeder). The same switch sits in Settings → Alerts and on the camera's sheet on the
 * map, and both save one camera at a time, so neither can undo the other.
 *
 * It saves the moment it is tapped and says what happened under it. The knob moves
 * at once; if the save fails it goes back and says why, rather than snapping back
 * with no word. While a save is out the row is held, so two quick taps can't cross.
 */
export default function CameraAlertRow({ id, name, alerts, label, note, onSaved }: {
  id: string
  name: string
  /** What the server last said. */
  alerts: boolean
  /** The row's words; the camera's name when left out (the Settings list). */
  label?: ReactNode
  note?: ReactNode
  onSaved?: (saved: Saved) => void
}) {
  const [pending, setPending] = useState<boolean | null>(null)
  const [said, setSaid] = useState<{ text: string; err: boolean } | null>(null)
  const on = pending ?? alerts

  // A different camera in the same sheet starts with nothing said.
  useEffect(() => { setSaid(null); setPending(null) }, [id])
  // "Saved" is news for a few seconds; a failure stays until the next tap.
  useEffect(() => {
    if (!said || said.err) return
    const t = window.setTimeout(() => setSaid(null), 8000)
    return () => window.clearTimeout(t)
  }, [said])

  async function change(next: boolean) {
    if (pending != null) return
    setPending(next)
    setSaid(null)
    try {
      const r = await api<Saved>(`/notifications/cameras/${encodeURIComponent(id)}`, {
        method: 'PUT', body: JSON.stringify({ alerts: next }), timeoutMs: 20_000,
      })
      onSaved?.(r)
      setSaid({ err: false, text: r.alerts ? `Saved. Alerts from ${name} are on.` : `Saved. No alerts from ${name}.` })
    } catch (e) {
      const x = e as Failure
      const why = x.offline ? 'No signal, so that didn’t save.' : x.timeout ? 'No answer from the server, so that didn’t save.' : `That didn’t save. ${x.message}`
      setSaid({ err: true, text: `${why} Alerts from ${name} are still ${alerts ? 'on' : 'off'}.` })
    } finally {
      setPending(null)
    }
  }

  return <>
    <SwitchRow label={label ?? name} note={pending != null ? 'Saving…' : note} on={on} onChange={change} disabled={pending != null} />
    {said && <p className={`switch-said${said.err ? ' switch-said--err' : ''}`} role={said.err ? 'alert' : 'status'}>{said.text}</p>}
  </>
}
