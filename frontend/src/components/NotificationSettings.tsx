import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ageLabel, api } from '../api'
import {
  currentSubscription,
  permission,
  pushSupport,
  subscribeThisDevice,
  unsubscribeThisDevice,
} from '../push'
import SettingsSection from './SettingsSection'
import Toggle from './Toggle'

type SpeciesPref = { id: string; common_name: string; selected: boolean; detections: number }
type Settings = {
  enabled: boolean
  configured: boolean
  species: SpeciesPref[]
  public_key: string
  subscriptions: number
}
type NotifRow = {
  id: string
  kind: string
  title: string
  body: string
  url: string | null
  push_status: string | null
  created_at: string
  read_at: string | null
}
type Feed = { unread: number; items: NotifRow[] }
type Device = 'checking' | 'subscribed' | 'not_subscribed'

const smallBtn = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text-dim)',
  borderRadius: 'var(--r-ctl)',
  padding: '5px 10px',
  fontSize: 12,
  cursor: 'pointer',
  flexShrink: 0,
} as const

const row = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 10,
  padding: '8px 0',
  borderTop: '1px solid var(--border)',
} as const

/**
 * Settings → Notifications.
 *
 * Two independent switches, deliberately: the account-level "Sighting alerts" (do I
 * want these at all, and about which animals) and this device's subscription. A
 * hunter with a phone and a tablet turns alerts on once and subscribes each device
 * from that device; turning alerts off silences all of them.
 */
export default function NotificationSettings() {
  const [s, setS] = useState<Settings | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [device, setDevice] = useState<Device>('checking')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [feed, setFeed] = useState<Feed | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)
  const support = pushSupport()

  async function refreshSettings(): Promise<Settings | null> {
    try {
      const next = await api<Settings>('/notifications/settings')
      setS(next)
      return next
    } catch (e) {
      setLoadErr((e as Error).message)
      return null
    }
  }

  async function refreshFeed() {
    try {
      const f = await api<Feed>('/notifications?limit=8')
      setFeed(f)
      // Seeing the list is reading it.
      if (f.unread > 0) api('/notifications/read', { method: 'POST' }).catch(() => {})
    } catch {
      /* the list is a convenience; the switches still work without it */
    }
  }

  useEffect(() => {
    refreshSettings()
    refreshFeed()
    currentSubscription().then((sub) => setDevice(sub ? 'subscribed' : 'not_subscribed'))
  }, [])

  async function setEnabled(next: boolean) {
    if (!s) return
    setBusy(true)
    setMsg('')
    setS({ ...s, enabled: next })
    try {
      await api('/notifications/settings', { method: 'PUT', body: JSON.stringify({ enabled: next }) })
      if (next) {
        if (support.ok) {
          await subscribeThisDevice(s.public_key)
          setDevice('subscribed')
          setMsg('On. This device will be told about new sightings.')
        }
      } else {
        await unsubscribeThisDevice()
        setDevice('not_subscribed')
      }
    } catch (e) {
      setMsg((e as Error).message)
    }
    await refreshSettings()
    setBusy(false)
  }

  async function subscribeHere() {
    if (!s) return
    setBusy(true)
    setMsg('')
    try {
      await subscribeThisDevice(s.public_key)
      setDevice('subscribed')
      setMsg('This device is now subscribed.')
    } catch (e) {
      setMsg((e as Error).message)
    }
    await refreshSettings()
    setBusy(false)
  }

  async function toggleSpecies(sp: SpeciesPref) {
    if (!s) return
    const before = s
    const species = s.species.map((x) => (x.id === sp.id ? { ...x, selected: !x.selected } : x))
    setSavingId(sp.id)
    setS({ ...s, species })
    try {
      await api('/notifications/settings', {
        method: 'PUT',
        body: JSON.stringify({ species_ids: species.filter((x) => x.selected).map((x) => x.id) }),
      })
    } catch {
      setS(before) // revert on failure
    }
    setSavingId(null)
  }

  async function sendTest() {
    setBusy(true)
    setMsg('')
    try {
      const r = await api<{ sent: number; failed: number; subscriptions: number }>(
        '/notifications/test',
        { method: 'POST' },
      )
      setMsg(
        r.sent
          ? `Sent to ${r.sent} device${r.sent === 1 ? '' : 's'}. It can take a few seconds to show.`
          : `Could not deliver to ${r.subscriptions} device${r.subscriptions === 1 ? '' : 's'}.`,
      )
      refreshFeed()
    } catch (e) {
      setMsg((e as Error).message)
    }
    setBusy(false)
  }

  const selected = s ? s.species.filter((x) => x.selected).length : 0
  const perm = permission()

  let deviceLine: string
  if (!support.ok) deviceLine = support.reason
  else if (perm === 'denied')
    deviceLine = 'Notifications are blocked for GameSense in this browser. Allow them in the site or phone settings to subscribe.'
  else if (device === 'checking') deviceLine = 'Checking this device…'
  else if (device === 'subscribed')
    deviceLine = s && s.subscriptions > 1
      ? `This device is subscribed (${s.subscriptions} devices in total).`
      : 'This device is subscribed.'
  else deviceLine = 'This device is not subscribed yet.'

  return (
    <SettingsSection id="notifications" title="Notifications"
      summary={s && s.species.length > 0 ? `${selected} of ${s.species.length} animals` : undefined}>
      <div style={{ fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5, marginBottom: 8 }}>
        A push on your phone when a camera catches an animal you care about. One message per
        species per sync, with the camera and the time, and never for photos older than a day.
      </div>

      {loadErr && !s ? (
        <div role="alert" style={{ fontSize: 13, color: 'var(--skip)', padding: '8px 0' }}>
          Couldn't load notification settings: {loadErr}
        </div>
      ) : !s ? (
        <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>Loading…</div>
      ) : (
        <>
          <div style={row}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14 }}>Sighting alerts</div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.4 }}>{deviceLine}</div>
            </div>
            <Toggle
              on={s.enabled}
              disabled={busy}
              onChange={() => setEnabled(!s.enabled)}
              label={s.enabled ? 'Sighting alerts on. Click to turn off.' : 'Sighting alerts off. Click to turn on.'}
            />
          </div>

          {s.enabled && support.ok && perm !== 'denied' && device === 'not_subscribed' && (
            <div style={{ padding: '4px 0 8px' }}>
              <button onClick={subscribeHere} disabled={busy} style={smallBtn}>
                Subscribe this device
              </button>
            </div>
          )}

          <div className="sect" style={{ marginTop: 14, marginBottom: 4 }}>
            Notify me about
          </div>
          {s.species.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>
              No animals identified yet. They appear here as the cameras see them.
            </div>
          ) : (
            s.species.map((sp) => (
              <div key={sp.id} style={row}>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, color: sp.selected ? 'var(--text)' : 'var(--text-dim)' }}>
                    {sp.common_name}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                    {sp.detections} sighting{sp.detections === 1 ? '' : 's'}
                  </div>
                </div>
                <Toggle
                  on={sp.selected}
                  disabled={savingId === sp.id}
                  onChange={() => toggleSpecies(sp)}
                  label={
                    sp.selected
                      ? `Notifying about ${sp.common_name}. Click to stop.`
                      : `Not notifying about ${sp.common_name}. Click to start.`
                  }
                />
              </div>
            ))
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
            <button
              onClick={sendTest}
              disabled={busy || device !== 'subscribed'}
              style={{ ...smallBtn, opacity: device !== 'subscribed' ? 0.6 : 1 }}
              title={device === 'subscribed' ? 'Push a test message to your devices' : 'Subscribe a device first'}
            >
              Send a test
            </button>
            {msg && <div style={{ fontSize: 13, color: 'var(--text-dim)', flex: 1, minWidth: 0 }}>{msg}</div>}
          </div>

          {feed && feed.items.length > 0 && (
            <>
              <div className="sect" style={{ marginTop: 16, marginBottom: 4 }}>
                Recent
              </div>
              {feed.items.map((n) => (
                <div key={n.id} style={{ ...row, alignItems: 'flex-start' }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    {n.url ? (
                      <Link to={n.url} style={{ fontSize: 14, color: 'var(--text)', textDecoration: 'underline', textUnderlineOffset: 3 }}>{n.title}</Link>
                    ) : (
                      <div style={{ fontSize: 14 }}>{n.title}</div>
                    )}
                    <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.4 }}>{n.body}</div>
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <div>{ageLabel(n.created_at)}</div>
                    {n.push_status && n.push_status !== 'sent' && (
                      <div title={n.push_status} style={{ color: 'var(--marginal)' }}>
                        {n.push_status === 'no_subscription' ? 'no device' : 'not delivered'}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </>
          )}
        </>
      )}
    </SettingsSection>
  )
}
