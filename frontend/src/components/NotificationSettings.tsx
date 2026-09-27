import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ageLabel, api } from '../api'
import {
  type DeviceState,
  applePush,
  askPermission,
  checkThisDevice,
  permission,
  pushSupport,
  subscribeThisDevice,
  unsubscribeThisDevice,
} from '../push'
import CameraAlertRow from './CameraAlerts'
import SettingsSection from './SettingsSection'
import SwitchRow from './SwitchRow'

type SpeciesPref = { id: string; common_name: string; selected: boolean; detections: number }
type CameraPref = { id: string; name: string; alerts: boolean }
type Settings = {
  enabled: boolean
  configured: boolean
  species: SpeciesPref[]
  cameras: CameraPref[]
  quiet_start: string | null
  quiet_end: string | null
  plan_push: boolean
  public_key: string
  subscriptions: number
}
/** What PUT /notifications/settings takes, and answers with what it saved. */
type Changes = { species_ids?: string[]; quiet?: boolean; quiet_start?: string; quiet_end?: string; plan_push?: boolean }
type Saved = { enabled: boolean; species_ids: string[]; quiet_start: string | null; quiet_end: string | null; plan_push: boolean }
type NotifRow = {
  id: string
  kind: string
  title: string
  body: string
  url: string | null
  push_status: string | null
  created_at: string
  read_at: string | null
  /** Quiet updates folded into this alert (its title and body are the latest one's). */
  updates?: number
  updated_at?: string | null
}
type Feed = { unread: number; items: NotifRow[] }
type Device = 'checking' | DeviceState
type Failure = Error & { offline?: boolean; timeout?: boolean }
/** Which part of the screen a save was about, so the line saying how it went sits under it. */
type Part = 'plan' | 'species' | 'quiet'

const smallBtn = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text-dim)',
  borderRadius: 'var(--r-ctl)',
  padding: '5px 12px',
  fontSize: 13,
  cursor: 'pointer',
  flexShrink: 0,
  minHeight: 44,
} as const

const row = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 10,
  padding: '8px 0',
  borderTop: '1px solid var(--border)',
} as const

// Taps this close together go to the server as one save.
const SAVE_AFTER_MS = 500
const QUIET_DEFAULT = { start: '23:00', end: '07:00' }

/** What happened to an alert, in the Recent list. Nothing for one that got through. */
const DELIVERY: Record<string, { text: string; warn?: boolean; why: string }> = {
  updated: { text: 'quiet update', why: 'Updated the alert already on your phone without buzzing again.' },
  held: { text: 'waiting', why: 'Held while you sit or during your quiet hours. It comes in one message after.' },
  in_summary: { text: 'in one message', why: 'Sent in the one message after your sit or quiet hours.' },
  skipped: { text: 'not sent', why: 'Not sent: you were sitting, in your quiet hours, or alerts were off.' },
  withdrawn: { text: 'not sent', why: 'Not sent: by the time it could go, the photo was marked “nothing in it”, or the animal hidden or switched off.' },
  no_subscription: { text: 'no device', warn: true, why: 'No phone was set up to get alerts.' },
  failed: { text: 'not delivered', warn: true, why: 'The phone didn’t take it.' },
}

/** The line over the camera switches, true to them: how many are on, and what muting does. */
function camerasHint(cameras: { alerts: boolean }[]): string {
  const on = cameras.filter((c) => c.alerts).length
  if (on === cameras.length) return 'Every camera is on. Mute a busy one, like a feeder, and you hear nothing from it. Only for you.'
  if (on === 0) return 'Every camera is muted, so you hear nothing from any of them. Only for you: the team still hears.'
  return `${on} of ${cameras.length} cameras on. A muted one sends you nothing; the team still hears from it. Only for you.`
}

/** Where the count goes while an animal stays: an iPhone buzzes for every push, so it
 *  only gets the buzz (the server leaves it out of the quiet updates). */
function rhythmHint(): string {
  return applePush()
    ? 'A message when a camera catches an animal you picked. One buzz per animal every two hours. On an iPhone, the count while it stays goes on in Recent below.'
    : 'A message when a camera catches an animal you picked. One buzz per animal every two hours: if it stays, the same alert updates quietly.'
}

function failWords(e: unknown): string {
  const x = e as Failure
  if (x.offline) return 'No signal, so that didn’t save.'
  if (x.timeout) return 'No answer from the server, so that didn’t save.'
  return `That didn’t save. ${x.message}`
}

/**
 * Settings → Alerts on my phone.
 *
 * Two independent switches: the account-level "Alerts" (do I want these at all,
 * and about which animals) and this device's push subscription. Alerts are turned
 * on once; each phone or tablet is then added from that device. Alerts off
 * silences all of them.
 *
 * What the phone line says is what the app found when it checked both sides: this
 * browser's subscription and the server's copy of it (push.checkThisDevice). It used
 * to ask the browser only, and said "This phone gets alerts" to a phone the server
 * had dropped (audit D-04).
 *
 * The animal switches, quiet hours and the plan switch save together a moment after
 * the last tap, one save at a time: quick taps used to cross on the way and leave the
 * server with a different list from the screen (audit D-14, I-14). When a save is
 * back the screen says so; when one fails it shows what the server has and says so,
 * rather than putting back a copy from before the tap. With no signal the server
 * can't be asked either, so the switches go back to the last copy it confirmed (on
 * opening, or at the last save that went through): never a choice that wasn't saved.
 *
 * The plan comes through Alerts: turning it on with Alerts off turns Alerts on from
 * the same tap, as the Alerts switch does, and says so. It used to say "Saved." and
 * never come.
 */
export default function NotificationSettings() {
  const [s, setS] = useState<Settings | null>(null)
  const [loadErr, setLoadErr] = useState('')
  const [device, setDevice] = useState<Device>('checking')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [feed, setFeed] = useState<Feed | null>(null)
  const [said, setSaid] = useState<{ part: Part; text: string; err: boolean } | null>(null)
  const support = pushSupport()

  // The save in the making: what changed since the last one went, whether one is on
  // its way, and the timer that sends it.
  const sRef = useRef(s)
  sRef.current = s
  const want = useRef<Changes>({})
  const wantPart = useRef<Part>('species')
  const sending = useRef(false)
  const timer = useRef(0)
  const alive = useRef(true)
  // What the server last said it has: from the last read, or the last save that
  // went through. What a failed save goes back to when the server can't be asked.
  const confirmed = useRef<Settings | null>(null)

  async function refreshSettings(): Promise<Settings | null> {
    try {
      const next = await api<Settings>('/notifications/settings')
      confirmed.current = next
      if (alive.current) setS(next)
      return next
    } catch (e) {
      if (alive.current) setLoadErr((e as Error).message)
      return null
    }
  }

  /** A save went through: the server's copy, as it answered. */
  function confirm(saved: Saved): Settings | null {
    const cur = confirmed.current
    if (!cur) return null
    confirmed.current = {
      ...cur,
      enabled: saved.enabled,
      species: cur.species.map((x) => ({ ...x, selected: saved.species_ids.includes(x.id) })),
      quiet_start: saved.quiet_start, quiet_end: saved.quiet_end, plan_push: saved.plan_push,
    }
    return confirmed.current
  }

  /** After a failed save: the switches show what the server has, asked again, or with
   *  no signal the last copy it confirmed. True when the server could be asked. */
  async function showSaved(): Promise<boolean> {
    const fresh = await refreshSettings()
    if (!fresh && alive.current && confirmed.current) setS(confirmed.current)
    return !!fresh
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

  async function checkDevice() {
    setDevice('checking')
    const state = await checkThisDevice()
    if (!alive.current) return
    setDevice(state)
    // The check may have put the server's copy back: the device count follows.
    if (state === 'subscribed') refreshSettings()
  }

  useEffect(() => {
    alive.current = true
    refreshSettings()
    refreshFeed()
    checkDevice()
    return () => {
      alive.current = false
      // Leaving the page with a save waiting sends it now rather than losing it.
      window.clearTimeout(timer.current)
      void send()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // "Saved" is news for a few seconds; a failure stays until the next change.
  useEffect(() => {
    if (!said || said.err || said.text !== 'Saved.') return
    const t = window.setTimeout(() => setSaid(null), 6000)
    return () => window.clearTimeout(t)
  }, [said])

  /** Queue `changes` (each field whole, as the screen shows it now) and send them
   *  a moment after the last tap. */
  function save(part: Part, changes: Changes) {
    Object.assign(want.current, changes)
    wantPart.current = part
    setSaid({ part, text: 'Saving…', err: false })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void send(), SAVE_AFTER_MS)
  }

  /** One save at a time; when it is back, the next if anything changed meanwhile. */
  async function send() {
    if (sending.current) return // the one on its way sends again when it is back
    const body = want.current
    if (Object.keys(body).length === 0) return
    want.current = {}
    const part = wantPart.current
    sending.current = true
    try {
      const saved = await api<Saved>('/notifications/settings', {
        method: 'PUT', body: JSON.stringify(body), timeoutMs: 20_000,
      })
      sending.current = false
      if (Object.keys(want.current).length > 0) {
        // Tapped again while this one was out: that is the newer choice. Its own
        // timer may still be running; it finds nothing left to send.
        void send()
        return
      }
      confirm(saved)
      if (!alive.current) return
      // The server's copy is what the screen shows from here.
      setS((cur) => cur && {
        ...cur,
        species: cur.species.map((x) => ({ ...x, selected: saved.species_ids.includes(x.id) })),
        quiet_start: saved.quiet_start, quiet_end: saved.quiet_end, plan_push: saved.plan_push,
      })
      setSaid({ part, err: false, text: 'Saved.' })
    } catch (e) {
      sending.current = false
      // What the server has wins over any tap still waiting: the screen shows it.
      want.current = {}
      window.clearTimeout(timer.current)
      const asked = await showSaved()
      if (!alive.current) return
      setSaid({
        part, err: true,
        text: `${failWords(e)} ${asked ? 'The switches show what is saved.' : 'The switches show what was saved last.'}`,
      })
    }
  }

  /** The Alerts switch; `withPlan` when the plan switch turned Alerts on with it. */
  async function setEnabled(next: boolean, withPlan = false) {
    if (!s) return
    // Asked first, straight from the tap: an iPhone shows the prompt only while the
    // tap is fresh, and the save below can take a while on one bar (audit D-19).
    const asked = next && support.ok && permission() !== 'denied' ? askPermission() : undefined
    asked?.catch(() => {})
    setBusy(true)
    setMsg('')
    setS({ ...s, enabled: next, plan_push: withPlan || s.plan_push })
    if (withPlan) setSaid({ part: 'plan', text: 'Saving…', err: false })
    let saved = false
    try {
      const changes = withPlan ? { enabled: next, plan_push: true } : { enabled: next }
      confirm(await api<Saved>('/notifications/settings', { method: 'PUT', body: JSON.stringify(changes), timeoutMs: 20_000 }))
      saved = true
      if (withPlan) {
        setSaid({
          part: 'plan', err: false,
          text: 'Saved. Alerts are on too: the plan comes with them. Switch off any animal below you don’t want to hear about.',
        })
      }
      if (next) {
        if (support.ok) {
          await subscribeThisDevice(s.public_key, asked)
          setDevice('subscribed')
          setMsg('On. This phone will get alerts.')
        }
      } else {
        await unsubscribeThisDevice()
        setDevice('not_subscribed')
      }
    } catch (e) {
      if (withPlan && !saved) setSaid({ part: 'plan', err: true, text: failWords(e) })
      else setMsg(saved ? (e as Error).message : failWords(e))
    }
    if (saved) await refreshSettings()
    else await showSaved()
    setBusy(false)
  }

  async function subscribeHere() {
    if (!s) return
    const asked = askPermission()
    asked.catch(() => {})
    setBusy(true)
    setMsg('')
    try {
      await subscribeThisDevice(s.public_key, asked)
      setDevice('subscribed')
      setMsg('This phone will get alerts.')
    } catch (e) {
      setMsg((e as Error).message)
    }
    await refreshSettings()
    setBusy(false)
  }

  function toggleSpecies(sp: SpeciesPref) {
    const cur = sRef.current
    if (!cur) return
    const species = cur.species.map((x) => (x.id === sp.id ? { ...x, selected: !x.selected } : x))
    setS({ ...cur, species })
    save('species', { species_ids: species.filter((x) => x.selected).map((x) => x.id) })
  }

  function setQuiet(start: string | null, end: string | null) {
    const cur = sRef.current
    if (!cur) return
    setS({ ...cur, quiet_start: start, quiet_end: end })
    if (start && end && start === end) {
      setSaid({ part: 'quiet', err: true, text: 'Quiet hours have to end at a different time from when they start.' })
      return
    }
    save('quiet', start && end ? { quiet: true, quiet_start: start, quiet_end: end } : { quiet: false })
  }

  function setPlan(on: boolean) {
    const cur = sRef.current
    if (!cur) return
    // The plan is sent to people with Alerts on: turning it on turns Alerts on too.
    if (on && !cur.enabled) return void setEnabled(true, true)
    setS({ ...cur, plan_push: on })
    save('plan', { plan_push: on })
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
          ? `Sent to ${r.sent} device${r.sent === 1 ? '' : 's'}. Give it a few seconds.`
          : `Didn't get through to ${r.subscriptions} device${r.subscriptions === 1 ? '' : 's'}.`,
      )
      refreshFeed()
    } catch (e) {
      setMsg((e as Error).message)
    }
    setBusy(false)
  }

  const selected = s ? s.species.filter((x) => x.selected).length : 0
  const perm = permission()
  const quietOn = !!(s?.quiet_start && s?.quiet_end)

  let deviceLine: string
  if (!support.ok) deviceLine = support.reason
  else if (perm === 'denied')
    deviceLine = 'Blocked in this browser. Allow notifications for GameSense in your phone settings.'
  else if (s && !s.enabled) deviceLine = 'Off. Nothing is sent to any of your phones.'
  else if (device === 'checking') deviceLine = 'Checking this phone…'
  else if (device === 'subscribed')
    deviceLine = s && s.subscriptions > 1
      ? `This phone gets alerts (${s.subscriptions} devices in total).`
      : 'This phone gets alerts.'
  else if (device === 'unconfirmed')
    deviceLine = 'Set up on this phone, but the server couldn’t be reached to check it.'
  else deviceLine = 'This phone is not getting alerts yet.'

  const saidUnder = (part: Part) => said?.part === part && (
    <p className={`switch-said${said.err ? ' switch-said--err' : ''}`} role={said.err ? 'alert' : 'status'}>{said.text}</p>
  )

  return (
    <SettingsSection id="notifications" title="Alerts on my phone"
      summary={s && s.species.length > 0 ? `${selected} of ${s.species.length} animals` : undefined}>
      <p className="settings-hint">{rhythmHint()}</p>

      {loadErr && !s ? (
        <div role="alert" style={{ fontSize: 13, color: 'var(--skip)', padding: '8px 0' }}>
          Couldn't load alert settings: {loadErr}
        </div>
      ) : !s ? (
        <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>Loading…</div>
      ) : (
        <>
          {/* The same whole-row switch as the cameras below and the map's sheets. */}
          <SwitchRow label="Alerts" note={deviceLine} on={s.enabled} disabled={busy} onChange={() => setEnabled(!s.enabled)} />

          {s.enabled && support.ok && perm !== 'denied' && (device === 'not_subscribed' || device === 'unconfirmed') && (
            <div style={{ padding: '4px 0 8px' }}>
              {device === 'not_subscribed' ? (
                <button onClick={subscribeHere} disabled={busy} style={smallBtn}>
                  Get alerts on this phone
                </button>
              ) : (
                <button onClick={() => void checkDevice()} disabled={busy} style={smallBtn}>
                  Check again
                </button>
              )}
            </div>
          )}

          <SwitchRow label="Tonight's plan before sunset" on={s.enabled && s.plan_push} onChange={setPlan} disabled={busy}
            note={s.enabled
              ? 'One message a day, about 2 hours before sunset: where, the wind and sunset. Quiet nights too.'
              : 'One message a day, about 2 hours before sunset. Turning it on turns Alerts on too.'} />
          {saidUnder('plan')}

          <div className="sect" style={{ marginTop: 14, marginBottom: 4 }}>
            Which animals
          </div>
          {s.species.length === 0 ? (
            <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>
              No animals yet. They show up here as the cameras see them.
            </div>
          ) : (
            s.species.map((sp) => (
              <SwitchRow key={sp.id} label={sp.common_name} on={sp.selected}
                note={`${sp.detections} sighting${sp.detections === 1 ? '' : 's'}`} onChange={() => toggleSpecies(sp)} />
            ))
          )}
          {saidUnder('species')}

          {s.cameras.length > 0 && (
            <>
              <div className="sect" style={{ marginTop: 14, marginBottom: 4 }}>
                Cameras
              </div>
              <p className="settings-hint">{camerasHint(s.cameras)}</p>
              {s.cameras.map((c) => (
                <CameraAlertRow
                  key={c.id}
                  id={c.id}
                  name={c.name}
                  alerts={c.alerts}
                  onSaved={(r) => {
                    const mark = (cur: Settings) => ({
                      ...cur, cameras: cur.cameras.map((x) => (x.id === c.id ? { ...x, alerts: r.alerts } : x)),
                    })
                    if (confirmed.current) confirmed.current = mark(confirmed.current)
                    setS((cur) => cur && mark(cur))
                  }}
                />
              ))}
            </>
          )}

          <div className="sect" style={{ marginTop: 14, marginBottom: 4 }}>
            When
          </div>
          <p className="settings-hint">Nothing buzzes while you sit (from Start sit to End sit). What came in arrives as one message when you end the sit.</p>
          <SwitchRow label="Quiet hours" on={quietOn}
            onChange={(on) => (on ? setQuiet(QUIET_DEFAULT.start, QUIET_DEFAULT.end) : setQuiet(null, null))}
            note={quietOn
              ? `Nothing buzzes from ${s.quiet_start} to ${s.quiet_end}. What comes in then arrives as one message after.`
              : 'Off. Alerts come at any hour.'} />
          {quietOn && (
            <div className="quiet-hours">
              <label>
                <span>From</span>
                <input className="input" type="time" required value={s.quiet_start ?? ''}
                  onChange={(e) => e.target.value && setQuiet(e.target.value, s.quiet_end)} />
              </label>
              <label>
                <span>To</span>
                <input className="input" type="time" required value={s.quiet_end ?? ''}
                  onChange={(e) => e.target.value && setQuiet(s.quiet_start, e.target.value)} />
              </label>
            </div>
          )}
          {saidUnder('quiet')}

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
            <button
              onClick={sendTest}
              disabled={busy || device !== 'subscribed'}
              style={{ ...smallBtn, opacity: device !== 'subscribed' ? 0.6 : 1 }}
              title={device === 'subscribed' ? 'Send a test alert to your devices' : 'Turn on alerts on a phone first'}
            >
              Send a test
            </button>
            {msg && <div role="status" style={{ fontSize: 13, color: 'var(--text-dim)', flex: 1, minWidth: 0 }}>{msg}</div>}
          </div>

          {feed && feed.items.length > 0 && (
            <>
              <div className="sect" style={{ marginTop: 16, marginBottom: 4 }}>
                Recent
              </div>
              {feed.items.map((n) => {
                const how = n.updates
                  ? {
                      text: `${n.updates} quiet update${n.updates === 1 ? '' : 's'}`,
                      why: 'The count while it stayed, without buzzing again. Not sent to an iPhone, which would buzz.',
                      warn: false,
                    }
                  : n.push_status ? DELIVERY[n.push_status] : undefined
                return (
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
                      <div>{ageLabel(n.updated_at || n.created_at)}</div>
                      {how && (
                        <div title={how.why} style={{ color: how.warn ? 'var(--marginal)' : undefined }}>
                          {how.text}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </>
          )}
        </>
      )}
    </SettingsSection>
  )
}
