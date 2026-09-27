import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ageLabel, api, changePassword, peekMe, plainWords, signOut, whoAmI } from '../api'
import { confirmSignOut } from '../sits'
import HarvestBook from '../components/HarvestBook'
import NotificationSettings from '../components/NotificationSettings'
import { resetChoices } from '../components/PhotoFix'
import PhoneProblems from '../components/PhoneProblems'
import SettingsSection from '../components/SettingsSection'
import Toggle from '../components/Toggle'

type Status = {
  cameras: number
  images: number
  detections: number
  empty: number
  last_sync: { status: string; at: string | null } | null
  // Suntek (FTP or email) photos waiting to be imported and parked after failing;
  // null when this server has no Suntek spool.
  suntek: { ready: number | null; failed: number | null } | null
  ai?: AiStatus
  sex_pass?: SexStatus
  // Free space where the photos are kept; `low` under 2 GB. Null when unreadable.
  disk?: { free_gb: number; total_gb: number; low: boolean } | null
}
/** The AI pass (app.ai.checking): its backlog, what it gave up on, why it stopped. */
type AiStatus = {
  waiting: number
  failed: number
  running_since: string | null
  last_run_at: string | null
  last_ok_at: string | null
  stopped: string | null
  last_error: string | null
  last_error_at: string | null
  // Where the whole story is on the server (pipeline.log).
  log_file?: string
}
/** The cloud stag/hind pass (app.ai.vision_sex). */
type SexStatus = {
  enabled: boolean
  running: boolean
  waiting: number
  last_run_at: string | null
  labelled: number | null
  stopped: string | null
  last_error: string | null
  last_error_at: string | null
}
type Check = {
  current: string
  latest: string | null
  update_available?: boolean
  update_command?: string
  error?: string
}
type Species = {
  id: string
  common_name: string
  /** What the app calls it unless an admin names it otherwise. */
  default_name?: string
  huntable: boolean
  hidden: boolean
  is_priority: boolean
  // The big game the evening advice is for (boar, deer, mouflon, ibex): anything else
  // in the advice was switched on by an older build.
  big_game?: boolean
  detections: number
}
type Me = { id: string; email: string; role: string }
type UserRow = { id: string; email: string; role: string; is_you: boolean }
type CameraProvider = 'spypoint' | 'ubox'
type ImportLimits = { interval: string; daily: string }
/** Whether a login still works, as the last fetch found it (app.ingestion.logins). */
type LoginStatus = {
  // busy: no fetch lately because a long job (the AI pass) holds the server.
  state: 'ok' | 'failing' | 'stale' | 'busy' | 'unknown' | 'off'
  error: string | null
  last_ok_at: string | null
  last_attempt_at: string | null
  // A new password would fix it (refused, signed out, unreadable), not a network blip.
  password_problem: boolean
  // Its cameras whose photos didn't come on the last fetch although the login worked.
  cameras_failing: number
  camera_error: string | null
}
type CamAccount = {
  id: string
  label: string
  username: string | null
  provider: CameraProvider
  owner: string | null
  // Added by someone since removed (their email): it kept fetching, and the admin
  // who removed them owns it now.
  added_by_removed?: string | null
  active: boolean
  // The estate's main SPYPOINT login, from the server's .env: shown, not removable here.
  primary: boolean
  cameras: number
  // Its first import is still running: `cameras` is what the provider listed.
  importing: boolean
  status: LoginStatus
  can_remove: boolean
  can_edit: boolean
  ubox_min_interval_seconds: number
  ubox_max_images_per_day: number
  last_import: {
    at: string | null
    status: string | null
    error: string | null
    downloaded: number
    interval_skipped: number
    daily_limit_skipped: number
    no_image: number
    failed: number
  } | null
}
// The fetch summary's status (app.ingestion.fetch), in words.
const FETCH_WORDS: Record<string, string> = {
  ok: 'Worked', partial: 'Partly worked', error: 'Failed',
  skipped: 'No camera logins', running: 'Running', never: 'Never run',
}
const NUDGE_KEY = 'gs.settings.advice-nudge-done'
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
/** One short line on the AI pass for the folded section: what matters first. */
/** "Fox, Rabbit and Badger". */
const andList = (names: string[]) =>
  names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0] ?? ''

function aiSummary(ai: AiStatus): { text: string; warn: boolean } {
  if (ai.stopped) return { text: 'Stopped', warn: true }
  if (ai.failed > 0) return { text: `${ai.failed} couldn’t be checked`, warn: true }
  if (ai.waiting > 0) return { text: `${ai.waiting} waiting`, warn: false }
  return { text: 'All checked', warn: false }
}
const providerName = (provider: CameraProvider) => provider === 'ubox' ? 'UBox Pro' : 'SPYPOINT'
const needsLook = (a: CamAccount) => a.active
  && (a.status.state === 'failing' || a.status.state === 'stale' || a.status.cameras_failing > 0)
/** "3 h", "2 d": how long, from ageLabel's "3 h ago". */
const forLabel = (iso: string) => ageLabel(iso).replace(/ ago$/, '')

/** One line on whether the login works, in words: what is wrong comes first. */
function loginLine(a: CamAccount): { text: string; warn: boolean } {
  const s = a.status
  if (!a.active) return { text: 'Another copy of this login is already fetched. Remove this one.', warn: false }
  if (a.importing) return { text: 'Fetching its photos for the first time…', warn: false }
  const where = a.primary && s.password_problem ? ' It is set in the server’s .env file (SPYPOINT_PASSWORD).' : ''
  if ((s.state === 'ok' || s.state === 'busy') && s.cameras_failing > 0) {
    const which = s.cameras_failing === 1 ? 'One of its cameras' : `${s.cameras_failing} of its cameras`
    return { text: `${which} didn’t come through on the last fetch. ${s.camera_error ?? ''}`.trim(), warn: true }
  }
  switch (s.state) {
    case 'failing':
      return { text: `${s.error ?? 'The last fetch failed.'}${where}`, warn: true }
    case 'stale':
      return {
        text: s.last_ok_at
          ? `No fetch has worked for ${forLabel(s.last_ok_at)}. Photos have stopped coming in.`
          : 'No fetch has worked yet. Photos have stopped coming in.',
        warn: true,
      }
    case 'busy':
      return { text: 'Busy going through new photos. Fetching carries on when that’s done.', warn: false }
    case 'ok':
      return { text: `Working. Last fetch ${s.last_ok_at ? ageLabel(s.last_ok_at) : 'just now'}.`, warn: false }
    default:
      return { text: 'Not fetched yet. Photos come in on the next fetch.', warn: false }
  }
}

function UboxImportFields({
  prefix, limits, onChange, disabled,
}: {
  prefix: string
  limits: ImportLimits
  onChange: (limits: ImportLimits) => void
  disabled: boolean
}) {
  return (
    <fieldset style={{ border: 0, margin: 0, padding: 0 }} disabled={disabled}>
      <legend style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Photo limits</legend>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <label htmlFor={`${prefix}-interval`} style={{ flex: '1 1 170px', fontSize: 13 }}>
          Minimum gap (seconds)
          <input id={`${prefix}-interval`} className="input" type="number" inputMode="numeric"
            min={10} max={3600} step={1} required value={limits.interval} style={{ marginTop: 5 }}
            aria-describedby={`${prefix}-help`}
            onChange={(e) => onChange({ ...limits, interval: e.target.value })} />
        </label>
        <label htmlFor={`${prefix}-daily`} style={{ flex: '1 1 170px', fontSize: 13 }}>
          Maximum photos per day
          <input id={`${prefix}-daily`} className="input" type="number" inputMode="numeric"
            min={1} max={5000} step={1} required value={limits.daily} style={{ marginTop: 5 }}
            aria-describedby={`${prefix}-help`}
            onChange={(e) => onChange({ ...limits, daily: e.target.value })} />
        </label>
      </div>
      <div id={`${prefix}-help`} style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, marginTop: 8 }}>
        Per camera, per day. Photos too close together or over the limit are not fetched, so some sightings can be missed.
      </div>
    </fieldset>
  )
}
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
// Glove-sized: the buttons a hunter needs when a login breaks.
const loginBtn = { ...smallBtn, minHeight: 44, padding: '8px 14px', fontSize: 13, color: 'var(--text)' } as const

/**
 * An animal's name in the app, which an admin can change: "Hare" for the hares and
 * rabbits the model can't tell apart, on an estate that has no rabbits. Every list,
 * chip, alert and gallery uses it. Tap the name to change it; "Use the app's name"
 * goes back to the one it started with.
 */
function SpeciesName({ sp, canEdit, onSaved }: { sp: Species; canEdit: boolean; onSaved: (s: Species) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(sp.common_name)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const field = `species-name-${sp.id}`

  async function save(name: string | null) {
    if (saving) return
    const clean = name === null ? null : name.replace(/\s+/g, ' ').trim()
    if (clean !== null && !clean) { setErr('Type a name first.'); return }
    if (clean === sp.common_name) { setEditing(false); return }
    setSaving(true)
    setErr('')
    try {
      const r = await api<Species>(`/species/${sp.id}`, { method: 'PATCH', body: JSON.stringify({ common_name: clean }), timeoutMs: 20_000 })
      // The photo viewer's "Wrong?" list offers it by its new name from now on.
      resetChoices()
      onSaved({ ...sp, common_name: r.common_name, default_name: r.default_name ?? sp.default_name })
      setEditing(false)
    } catch (e) {
      const x = e as Error & { offline?: boolean; timeout?: boolean }
      setErr(x.offline ? 'No signal, so the name wasn’t saved.' : x.timeout ? 'No answer from the server, so the name wasn’t saved.' : `The name wasn’t saved. ${x.message}`)
    } finally {
      setSaving(false)
    }
  }

  const style = { fontSize: 14, color: sp.huntable ? 'var(--text)' : 'var(--text-dim)' }
  if (!canEdit) return <div style={style}>{sp.common_name}</div>
  if (!editing) {
    return (
      <button type="button" className="species-name" style={style} aria-label={`Rename ${sp.common_name}`}
        onClick={() => { setDraft(sp.common_name); setErr(''); setEditing(true) }}>
        {sp.common_name}
      </button>
    )
  }
  return (
    <form className="species-name-form" aria-busy={saving} onSubmit={(e) => { e.preventDefault(); void save(draft) }}
      onKeyDown={(e) => { if (e.key === 'Escape' && !saving) { e.preventDefault(); setEditing(false) } }}>
      <label htmlFor={field} className="sr-only">Name for {sp.common_name}</label>
      <input id={field} className="input" value={draft} maxLength={40} autoFocus disabled={saving}
        aria-invalid={!!err} onChange={(e) => { setDraft(e.target.value); setErr('') }} />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <button type="submit" style={loginBtn} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        <button type="button" style={loginBtn} disabled={saving} onClick={() => setEditing(false)}>Cancel</button>
        {sp.default_name && sp.default_name !== sp.common_name && (
          <button type="button" style={loginBtn} disabled={saving} onClick={() => void save(null)}>
            Use the app’s name ({sp.default_name})
          </button>
        )}
      </div>
      {err && <p role="alert" style={{ margin: 0, fontSize: 13, color: 'var(--skip)' }}>{err}</p>}
    </form>
  )
}

export default function Admin() {
  const nav = useNavigate()
  const [version, setVersion] = useState('')
  const [status, setStatus] = useState<Status | null>(null)
  const [check, setCheck] = useState<Check | null>(null)
  const [checking, setChecking] = useState(false)
  const [sexMsg, setSexMsg] = useState('')
  const [sexBusy, setSexBusy] = useState(false)
  const [retryBusy, setRetryBusy] = useState(false)
  const [retryMsg, setRetryMsg] = useState('')
  const [nudgeGone, setNudgeGone] = useState(() => {
    try { return localStorage.getItem(NUDGE_KEY) === '1' } catch { return false }
  })
  const [species, setSpecies] = useState<Species[]>([])
  const [speciesErr, setSpeciesErr] = useState('')
  const [savingId, setSavingId] = useState<string | null>(null)
  const [me, setMe] = useState<Me | null>(() => peekMe())
  const [users, setUsers] = useState<UserRow[]>([])
  const [newUser, setNewUser] = useState({ email: '', password: '', role: 'member' })
  const [userMsg, setUserMsg] = useState('')
  const [accounts, setAccounts] = useState<CamAccount[]>([])
  const [newAcct, setNewAcct] = useState({
    username: '', password: '', label: '', provider: 'spypoint' as CameraProvider,
    interval: '60', daily: '500',
  })
  const [acctMsg, setAcctMsg] = useState('')
  const [acctBusy, setAcctBusy] = useState(false)
  const [editingLimits, setEditingLimits] = useState<(ImportLimits & { id: string }) | null>(null)
  const [limitsBusy, setLimitsBusy] = useState(false)
  // A login's password being typed in again (it changed, or can't be read here).
  const [reentering, setReentering] = useState<{ id: string; password: string } | null>(null)
  const [reenterBusy, setReenterBusy] = useState(false)
  const [reenterMsg, setReenterMsg] = useState<{ id: string; text: string } | null>(null)
  const importPoll = useRef<number | null>(null)
  const [pw, setPw] = useState({ current: '', next: '' })
  const [pwMsg, setPwMsg] = useState('')
  // Only an admin changes the animals, the people and the server's own settings; the
  // server refuses anyone else, so nobody else is offered them (audit D-12, I-15).
  const admin = me?.role === 'admin'
  const viewer = me?.role === 'viewer'

  async function runSexPass() {
    setSexBusy(true)
    try {
      const r = await api<{ note?: string }>('/admin/sex-pass', { method: 'POST' })
      setSexMsg(r.note || 'Started.')
      loadStatus()
    } catch (e) {
      setSexMsg((e as Error).message)
    }
    setSexBusy(false)
  }

  function loadStatus() {
    api<Status>('/admin/status').then(setStatus).catch(() => {})
  }

  async function retryFailed() {
    setRetryBusy(true)
    try {
      const r = await api<{ note: string }>('/admin/ai/retry', { method: 'POST' })
      setRetryMsg(r.note)
      loadStatus()
    } catch (e) {
      setRetryMsg((e as Error).message)
    }
    setRetryBusy(false)
  }

  // Once, for the animals an older build put in the advice (dogs, sheep, birds…).
  async function adviceGameOnly(list: Species[]) {
    setSavingId('nudge')
    try {
      for (const sp of list) {
        await api(`/species/${sp.id}`, { method: 'PATCH', body: JSON.stringify({ huntable: false }) })
        setSpecies((all) => all.map((x) => (x.id === sp.id ? { ...x, huntable: false } : x)))
      }
      dismissNudge()
    } catch (e) {
      setSpeciesErr((e as Error).message)
    }
    setSavingId(null)
  }

  function dismissNudge() {
    setNudgeGone(true)
    try { localStorage.setItem(NUDGE_KEY, '1') } catch { /* private window: asks again next time */ }
  }

  useEffect(() => {
    loadSpecies()
    whoAmI().then(setMe).catch(() => {})
    api<CamAccount[]>('/camera-accounts').then(setAccounts).catch(() => {})
    return () => { if (importPoll.current) window.clearTimeout(importPoll.current) }
  }, [])
  // The admin-only parts, once it is known this is an admin: nobody else is answered.
  useEffect(() => {
    if (!admin) return
    api<{ version: string }>('/admin/version').then((r) => setVersion(r.version)).catch(() => {})
    loadStatus()
    api<UserRow[]>('/users').then(setUsers).catch(() => {})
  }, [admin])

  // A login just added imports in the background: look again every few seconds, for
  // two minutes at most, so its cameras and "Working" show without a reload.
  function followImport(tries = 24) {
    if (importPoll.current) window.clearTimeout(importPoll.current)
    importPoll.current = window.setTimeout(async () => {
      try {
        const list = await api<CamAccount[]>('/camera-accounts')
        setAccounts(list)
        if (tries > 1 && list.some((a) => a.importing)) followImport(tries - 1)
      } catch {
        if (tries > 1) followImport(tries - 1)
      }
    }, 5000)
  }

  async function reenterPassword() {
    if (!reentering || !reentering.password) return
    setReenterBusy(true)
    setReenterMsg(null)
    const { id } = reentering
    try {
      const r = await api<{ note: string }>(`/camera-accounts/${id}/password`, {
        method: 'PUT',
        body: JSON.stringify({ password: reentering.password }),
      })
      setReentering(null)
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
      setReenterMsg({ id, text: r.note })
    } catch (e) {
      setReenterMsg({ id, text: (e as Error).message })
    } finally {
      setReenterBusy(false)
    }
  }

  // Its own failure, in words: a swallowed one left the list on "Loading…" for good (audit I-10).
  function loadSpecies() {
    setSpeciesErr('')
    api<Species[]>('/species', { timeoutMs: 20_000 }).then(setSpecies).catch((e) => setSpeciesErr((e as Error).message))
  }

  async function addUser() {
    setUserMsg('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(newUser) })
      setNewUser({ email: '', password: '', role: 'member' })
      setUsers(await api<UserRow[]>('/users'))
      setUserMsg('Added')
    } catch (e) {
      setUserMsg((e as Error).message)
    }
  }

  async function delUser(u: UserRow) {
    if (!window.confirm(`Remove ${u.email}? They can't sign in any more, on any phone. What they recorded stays, and camera logins they added keep fetching photos, under your name.`)) return
    setUserMsg('')
    try {
      const r = await api<{ note: string; camera_logins_moved: number }>(`/users/${u.id}`, { method: 'DELETE' })
      setUsers(await api<UserRow[]>('/users'))
      setUserMsg(r.note)
      if (r.camera_logins_moved) setAccounts(await api<CamAccount[]>('/camera-accounts'))
    } catch (e) {
      setUserMsg((e as Error).message)
    }
  }

  async function addAccount() {
    setAcctMsg('')
    setAcctBusy(true)
    try {
      const r = await api<{ note?: string }>('/camera-accounts', {
        method: 'POST',
        body: JSON.stringify({
          username: newAcct.username,
          password: newAcct.password,
          label: newAcct.label || null,
          provider: newAcct.provider,
          ubox_min_interval_seconds: Number(newAcct.interval),
          ubox_max_images_per_day: Number(newAcct.daily),
        }),
      })
      setNewAcct({ ...newAcct, username: '', password: '', label: '' })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
      setAcctMsg(r.note || 'Added')
      followImport()
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
    setAcctBusy(false)
  }

  async function saveImportLimits() {
    if (!editingLimits) return
    setAcctMsg('')
    setLimitsBusy(true)
    try {
      const r = await api<{ note: string }>(`/camera-accounts/${editingLimits.id}/import-settings`, {
        method: 'PATCH',
        body: JSON.stringify({
          ubox_min_interval_seconds: Number(editingLimits.interval),
          ubox_max_images_per_day: Number(editingLimits.daily),
        }),
      })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
      setEditingLimits(null)
      setAcctMsg(r.note)
    } catch (e) {
      setAcctMsg((e as Error).message)
    } finally {
      setLimitsBusy(false)
    }
  }

  async function delAccount(a: CamAccount) {
    if (!window.confirm(`Remove ${a.label}? Photos already fetched stay. New ones stop.`)) return
    setAcctMsg('')
    try {
      await api(`/camera-accounts/${a.id}`, { method: 'DELETE' })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
  }

  async function changePw() {
    setPwMsg('')
    try {
      const note = await changePassword(pw.current, pw.next)
      setPw({ current: '', next: '' })
      setPwMsg(note)
    } catch (e) {
      setPwMsg((e as Error).message)
    }
  }

  async function toggleSpecies(s: Species) {
    const next = !s.huntable
    setSavingId(s.id)
    setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, huntable: next } : x)))
    setSpeciesErr('')
    try {
      await api(`/species/${s.id}`, { method: 'PATCH', body: JSON.stringify({ huntable: next }) })
    } catch (e) {
      // Back as it was, and why: a switch that just flips back reads as a bug.
      setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, huntable: !next } : x)))
      setSpeciesErr(`${s.common_name} wasn’t changed. ${(e as Error).message}`)
    }
    setSavingId(null)
  }

  // Hidden animals (rabbits) leave the whole app: photos, counts, alerts, advice.
  async function hideSpecies(s: Species, hidden: boolean) {
    setSavingId(s.id)
    const before = s
    setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, hidden, huntable: hidden ? false : x.huntable } : x)))
    setSpeciesErr('')
    try {
      await api(`/species/${s.id}`, { method: 'PATCH', body: JSON.stringify({ hidden }) })
      resetChoices()
    } catch (e) {
      setSpecies((list) => list.map((x) => (x.id === s.id ? before : x)))
      setSpeciesErr(`${s.common_name} wasn’t changed. ${(e as Error).message}`)
    }
    setSavingId(null)
  }

  async function checkUpdates() {
    setChecking(true)
    try {
      setCheck(await api<Check>('/admin/version/check'))
    } catch (e) {
      setCheck({ current: version, latest: null, error: (e as Error).message })
    }
    setChecking(false)
  }

  const rows: [string, number][] = status
    ? [
        ['Cameras', status.cameras],
        ['Photos', status.images],
        ['Animals spotted', status.detections],
        ['Empty photos skipped', status.empty],
      ]
    : []

  const shown = species.filter((s) => !s.hidden)
  const notGame = shown.filter((s) => s.huntable && s.big_game === false)
  const hiddenOnes = species.filter((s) => s.hidden)
  const onCount = shown.filter((s) => s.huntable).length

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <h1 className="page-title">Settings</h1>

      <SettingsSection id="advice" title="Animals in the advice"
        summary={species.length > 0 ? `${onCount} of ${shown.length} on` : undefined}>
        {admin || !me ? (
          <p className="settings-hint">Turn off anything you don't hunt or that's out of season. Hide an animal to keep it out of photos, counts and alerts too.{admin ? ' Tap a name to change what the app calls it.' : ''}</p>
        ) : (
          <p className="settings-hint" data-readonly="advice">The animals the evening advice is about. Only an admin can change them.</p>
        )}
        {speciesErr && species.length > 0 && <p role="alert" style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--skip)' }}>{speciesErr}</p>}
        {!nudgeGone && admin && notGame.length > 0 && (
          <div className="status-panel" data-nudge style={{ marginBottom: 10 }}>
            {andList(notGame.map((sp) => sp.common_name))} {notGame.length === 1 ? 'is' : 'are'} in the evening
            advice, which is meant for big game. Other animals new to the cameras now start switched off.
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              <button type="button" style={loginBtn} disabled={savingId === 'nudge'} onClick={() => adviceGameOnly(notGame)}>
                {savingId === 'nudge' ? 'Turning off…' : 'Turn them off'}
              </button>
              <button type="button" style={loginBtn} onClick={dismissNudge}>Keep them</button>
            </div>
          </div>
        )}
        {species.length === 0 ? (
          speciesErr ? (
            <div role="alert" style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>
              Couldn’t load the animals. {speciesErr}
              <button className="text-action" onClick={loadSpecies}>Try again</button>
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>Loading…</div>
          )
        ) : (
          shown.map((s) => (
            <div
              key={s.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 0',
                borderTop: '1px solid var(--border)',
              }}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <SpeciesName sp={s} canEdit={admin}
                  onSaved={(next) => setSpecies((list) => list.map((x) => (x.id === next.id ? next : x)))} />
                <div style={{ fontSize: 11, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                  {s.detections} sighting{s.detections === 1 ? '' : 's'}
                </div>
              </div>
              {admin ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button type="button" style={smallBtn} disabled={savingId === s.id}
                    aria-label={`Hide ${s.common_name} everywhere`} onClick={() => hideSpecies(s, true)}>
                    Hide
                  </button>
                  <Toggle
                    on={s.huntable}
                    disabled={savingId === s.id}
                    onChange={() => toggleSpecies(s)}
                    label={`${s.common_name} in the advice`}
                  />
                </div>
              ) : (
                <span style={{ fontSize: 13, color: s.huntable ? 'var(--text)' : 'var(--text-dim)' }}>
                  {s.huntable ? 'In the advice' : 'Off'}
                </span>
              )}
            </div>
          ))
        )}
        {hiddenOnes.length > 0 && (
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>Hidden everywhere</div>
            {hiddenOnes.map((s) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '6px 0' }}>
                <div style={{ fontSize: 14, color: 'var(--text-dim)' }}>{s.common_name}</div>
                {admin && <button type="button" style={smallBtn} disabled={savingId === s.id}
                  aria-label={`Show ${s.common_name} again`} onClick={() => hideSpecies(s, false)}>
                  Show again
                </button>}
              </div>
            ))}
          </div>
        )}
      </SettingsSection>

      <NotificationSettings />

      <SettingsSection id="accounts" title="Camera logins"
        summary={accounts.some(needsLook)
          ? <span style={{ color: 'var(--skip)' }}>{accounts.filter(needsLook).length} need{accounts.filter(needsLook).length === 1 ? 's' : ''} attention</span>
          : accounts.length > 0 ? `${accounts.length} login${accounts.length === 1 ? '' : 's'}` : undefined}>
        <p className="settings-hint">Add a SPYPOINT or UBox Pro login and its cameras join the estate.</p>
        {accounts.map((a) => {
          const line = loginLine(a)
          return (
          <div key={a.id} data-login={a.id} style={{ padding: '12px 0', borderTop: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
              <div style={{ minWidth: 0, flex: '1 1 200px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: 7 }}>
                  <span style={{ fontSize: 14, overflowWrap: 'anywhere' }}>{a.label}</span>
                  <span style={{ fontSize: 11, color: 'var(--text-dim)', border: '1px solid var(--border)', borderRadius: 'var(--r-chip)', padding: '1px 6px' }}>
                    {providerName(a.provider)}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)', overflowWrap: 'anywhere' }}>
                  {a.cameras} camera{a.cameras === 1 ? '' : 's'}{a.primary ? ' · the estate’s own' : a.added_by_removed ? '' : a.owner ? ` · added by ${a.owner}` : ''}
                </div>
                {a.added_by_removed && (
                  <div data-removed-owner style={{ fontSize: 12, color: 'var(--sand)', overflowWrap: 'anywhere', marginTop: 2 }}>
                    Added by {a.added_by_removed}, who was removed. It still fetches photos{a.owner ? `; ${a.owner} looks after it now` : ''}.
                  </div>
                )}
                <div className="login-status" data-state={a.importing ? 'importing' : a.status.state} role={line.warn ? 'alert' : undefined}
                  style={{ fontSize: 13, lineHeight: 1.45, marginTop: 4, color: line.warn ? 'var(--skip)' : 'var(--text-dim)' }}>
                  {line.text}
                </div>
              </div>
              {a.can_remove && (
                <button type="button" onClick={() => delAccount(a)} style={loginBtn}
                  disabled={limitsBusy} aria-label={`Remove ${a.label}`}>Remove</button>
              )}
            </div>
            {a.can_edit && !a.primary && a.active && reentering?.id !== a.id && a.status.password_problem && (
              <button type="button" style={{ ...loginBtn, marginTop: 8 }} onClick={() => { setReenterMsg(null); setReentering({ id: a.id, password: '' }) }}
                aria-label={`Re-enter the password for ${a.label}`}>Re-enter password</button>
            )}
            {reentering?.id === a.id && (
              <form onSubmit={(e) => { e.preventDefault(); void reenterPassword() }} style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
                <label htmlFor={`reenter-${a.id}`} style={{ fontSize: 13 }}>
                  {providerName(a.provider)} password for {a.username}
                  <input id={`reenter-${a.id}`} className="input" type="password" required autoFocus value={reentering.password}
                    disabled={reenterBusy} style={{ marginTop: 5 }} autoComplete="new-password"
                    onChange={(e) => setReentering({ id: a.id, password: e.target.value })} />
                </label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn" type="submit" disabled={reenterBusy || !reentering.password} style={{ width: 'auto', padding: '9px 14px', minHeight: 44 }}>
                    {reenterBusy ? `Checking with ${providerName(a.provider)}…` : 'Save password'}
                  </button>
                  <button type="button" style={loginBtn} disabled={reenterBusy} onClick={() => setReentering(null)}>Cancel</button>
                </div>
              </form>
            )}
            {reenterMsg?.id === a.id && <div role="status" style={{ marginTop: 8, fontSize: 13, color: 'var(--text-dim)' }}>{reenterMsg.text}</div>}
            {a.provider === 'ubox' && editingLimits?.id !== a.id && (
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <div style={{ fontSize: 12, color: 'var(--text-dim)', flex: '1 1 200px' }}>
                  Per camera: at least {a.ubox_min_interval_seconds}s apart,
                  {' '}up to {a.ubox_max_images_per_day} photos/day.
                </div>
                {a.can_edit && <button type="button" style={smallBtn} disabled={limitsBusy}
                  aria-label={`Edit photo limits for ${a.label}`}
                  onClick={() => setEditingLimits({
                    id: a.id, interval: String(a.ubox_min_interval_seconds), daily: String(a.ubox_max_images_per_day),
                  })}>Edit limits</button>}
              </div>
            )}
            {a.provider === 'ubox' && a.last_import && (
              <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, marginTop: 8 }}>
                Last fetch{a.last_import.at ? ` (${new Date(a.last_import.at).toLocaleString()})` : ''}:
                {' '}{a.last_import.downloaded} photos added,
                {' '}{a.last_import.interval_skipped} skipped (too close together),
                {' '}{a.last_import.daily_limit_skipped} skipped (daily limit).
                {a.last_import.no_image > 0 && ` ${a.last_import.no_image} had no photo.`}
                {a.last_import.failed > 0 && ` ${a.last_import.failed} failed.`}
                {a.last_import.error && a.last_import.error !== a.status.error && <div style={{ marginTop: 4 }}>Problem: {a.last_import.error}</div>}
              </div>
            )}
            {a.provider === 'ubox' && editingLimits?.id === a.id && (
              <form onSubmit={(e) => { e.preventDefault(); void saveImportLimits() }} style={{ marginTop: 14 }}>
                <UboxImportFields prefix={`account-${a.id}`} limits={editingLimits} disabled={limitsBusy}
                  onChange={(limits) => setEditingLimits({ id: a.id, ...limits })} />
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn" type="submit" disabled={limitsBusy} style={{ width: 'auto', padding: '8px 12px' }}>
                    {limitsBusy ? 'Saving…' : 'Save limits'}
                  </button>
                  <button type="button" style={smallBtn} disabled={limitsBusy}
                    onClick={() => setEditingLimits(null)}>Cancel</button>
                </div>
              </form>
            )}
          </div>
          )
        })}
        {viewer ? (
          <p className="settings-hint" style={{ marginTop: 10 }}>Members and admins add camera logins.</p>
        ) : (
        <form onSubmit={(e) => { e.preventDefault(); void addAccount() }}
          style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
          <label htmlFor="camera-provider" style={{ fontSize: 13 }}>
            Camera brand
            <select id="camera-provider" className="input" value={newAcct.provider} disabled={acctBusy}
              style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, provider: e.target.value as CameraProvider })}>
              <option value="spypoint">SPYPOINT</option>
              <option value="ubox">UBox Pro</option>
            </select>
          </label>
          <label htmlFor="camera-email" style={{ fontSize: 13 }}>
            {providerName(newAcct.provider)} email
            <input id="camera-email" className="input" type="email" required value={newAcct.username}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, username: e.target.value })} autoComplete="off" />
          </label>
          <label htmlFor="camera-password" style={{ fontSize: 13 }}>
            {providerName(newAcct.provider)} password
            <input id="camera-password" className="input" type="password" required value={newAcct.password}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, password: e.target.value })} autoComplete="new-password" />
          </label>
          <label htmlFor="camera-label" style={{ fontSize: 13 }}>
            Name (optional)
            <input id="camera-label" className="input" placeholder="e.g. Marco's cameras" value={newAcct.label}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, label: e.target.value })} />
          </label>
          {newAcct.provider === 'ubox' && (
            <UboxImportFields prefix="new-account" limits={newAcct} disabled={acctBusy}
              onChange={(limits) => setNewAcct({ ...newAcct, ...limits })} />
          )}
          <button className="btn" type="submit" style={{ width: 'auto', padding: '9px 14px' }}
            disabled={acctBusy || !newAcct.username.trim() || !newAcct.password}>
            {acctBusy ? `Checking with ${providerName(newAcct.provider)}…` : 'Add login'}
          </button>
        </form>
        )}
        {acctMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{acctMsg}</div>}
      </SettingsSection>

      {me && !viewer && <HarvestBook admin={admin} />}

      {admin && (
        <SettingsSection id="people" title="Who can sign in"
          summary={users.length > 0 ? `${users.length} ${users.length === 1 ? 'person' : 'people'}` : undefined}>
          <p className="settings-hint">Members see everything, reserve stands and add camera logins. Admins can also change settings. Removing someone keeps what they recorded.</p>
          {users.map((u) => (
            <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {u.email}{u.is_you ? ' (you)' : ''}
              </div>
              <span style={{ fontSize: 11, color: u.role === 'admin' ? 'var(--sand)' : 'var(--text-dim)', border: '1px solid var(--border)', borderRadius: 'var(--r-ctl)', padding: '1px 7px' }}>
                {u.role}
              </span>
              {!u.is_you && <button onClick={() => delUser(u)} style={smallBtn} aria-label={`Remove ${u.email}`}>Remove</button>}
            </div>
          ))}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
            <input className="input" placeholder="Email" aria-label="Email for the new person" value={newUser.email}
              onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} autoComplete="off" />
            <input className="input" placeholder="Password (at least 8 characters)" aria-label="Password for the new person" value={newUser.password}
              onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} autoComplete="new-password" />
            <div style={{ display: 'flex', gap: 8 }}>
              <select className="input" style={{ width: 130 }} value={newUser.role} aria-label="Role"
                onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
              <button className="btn" style={{ width: 'auto', padding: '9px 14px' }}
                onClick={addUser} disabled={!newUser.email || newUser.password.length < 8}>
                Add person
              </button>
            </div>
          </div>
          {userMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{userMsg}</div>}
        </SettingsSection>
      )}

      <SettingsSection id="password" title="Password">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input className="input" placeholder="Current password" aria-label="Current password" type="password" value={pw.current}
            onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
          <input className="input" placeholder="New password (at least 8 characters)" aria-label="New password" type="password" value={pw.next}
            onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
          <button className="btn" style={{ width: 'auto', padding: '9px 14px' }}
            onClick={changePw} disabled={!pw.current || pw.next.length < 8}>
            Change password
          </button>
        </div>
        {pwMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{pwMsg}</div>}
      </SettingsSection>

      {admin && <SettingsSection id="version" title="App version" summary={version ? `v${version}` : undefined}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>GameSense v{version || '…'}</div>
        <button
          className="btn"
          style={{ width: 'auto', marginTop: 12, padding: '8px 14px' }}
          onClick={checkUpdates}
          disabled={checking}
        >
          {checking ? 'Checking…' : 'Check for updates'}
        </button>
        {check && (
          <div style={{ marginTop: 12, fontSize: 13 }}>
            {check.error ? (
              <span style={{ color: 'var(--text-dim)' }}>Couldn't check for updates: {check.error}</span>
            ) : check.update_available ? (
              <>
                <div style={{ color: 'var(--go)' }}>
                  Update available: {check.latest} (you have {check.current})
                </div>
                <div style={{ color: 'var(--text-dim)', marginTop: 6 }}>How to update:</div>
                <code
                  style={{
                    display: 'block',
                    background: 'var(--surface-2)',
                    padding: '8px 10px',
                    borderRadius: 'var(--r-ctl)',
                    marginTop: 4,
                    fontSize: 12,
                    fontFamily: 'var(--font-mono, monospace)',
                  }}
                >
                  {check.update_command}
                </code>
              </>
            ) : (
              <span style={{ color: 'var(--text-dim)' }}>Up to date ({check.current}).</span>
            )}
          </div>
        )}
      </SettingsSection>}

      {admin && status?.ai && (() => {
        const ai = status.ai
        const sex = status.sex_pass
        const sum = aiSummary(ai)
        return (
          <SettingsSection id="ai" title="Photo checking"
            summary={<span style={{ color: sum.warn ? 'var(--skip)' : undefined }}>{sum.text}</span>}>
            {ai.stopped ? (
              <div role="alert" data-ai="stopped" style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--skip)' }}>
                New photos aren’t being checked for animals. {plainWords(ai.stopped)} They show as “Not checked
                yet” until it’s fixed. It tries again on every fetch. If it keeps happening, the detail is
                below{ai.log_file ? <> and in <span style={{ overflowWrap: 'anywhere' }}>{ai.log_file}</span> on the server</> : null}.
              </div>
            ) : ai.waiting > 0 ? (
              <div data-ai="waiting" style={{ fontSize: 14, lineHeight: 1.5 }}>
                {plural(ai.waiting, 'photo')} waiting to be checked for animals.{' '}
                {ai.running_since ? 'Checking now.' : 'A few hundred go through on every fetch, newest first.'}
              </div>
            ) : ai.failed === 0 ? (
              <div data-ai="ok" style={{ fontSize: 14, lineHeight: 1.5 }}>
                Every photo has been checked for animals{ai.last_run_at ? `. Last look ${ageLabel(ai.last_run_at)}.` : '.'}
              </div>
            ) : null}
            {ai.failed > 0 && (
              // The lead when nothing is waiting: never under "every photo has been checked".
              <div data-ai="failed" style={{ marginTop: ai.stopped || ai.waiting > 0 ? 10 : 0, fontSize: ai.stopped || ai.waiting > 0 ? 13 : 14, lineHeight: 1.5 }}>
                <div>
                  {plural(ai.failed, 'photo')} couldn’t be checked after 3 tries. They count as not checked, never as
                  empty nights.
                </div>
                <button type="button" style={{ ...loginBtn, marginTop: 8 }} onClick={retryFailed} disabled={retryBusy}>
                  {retryBusy ? 'Starting…' : 'Try them again'}
                </button>
              </div>
            )}
            {retryMsg && <div role="status" style={{ marginTop: 8, fontSize: 13, color: 'var(--text-dim)' }}>{retryMsg}</div>}
            {(ai.stopped || ai.last_error) && (
              <details style={{ marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
                <summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>
                  {ai.stopped ? 'The detail' : 'Last problem'}{ai.last_error_at ? `, ${ageLabel(ai.last_error_at)}` : ''}
                </summary>
                <div style={{ overflowWrap: 'anywhere' }}>{ai.stopped ?? ai.last_error}</div>
              </details>
            )}

            <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>Stags, hinds and boar</div>
              <p className="settings-hint" style={{ marginTop: 4 }}>Marks red deer as stag or hind, and wild boar as male or female, every hour.</p>
              {sex && !sex.enabled ? (
                <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>Needs an Anthropic key (ANTHROPIC_API_KEY) in the server’s .env.</div>
              ) : sex?.stopped ? (
                <div role="alert" data-sex="stopped" style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--skip)' }}>
                  Labelling stopped{sex.last_run_at ? ` ${ageLabel(sex.last_run_at)}` : ''}: {sex.stopped}
                </div>
              ) : sex ? (
                <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {sex.running ? 'Labelling now…' : sex.waiting > 0 ? `${plural(sex.waiting, 'photo')} to label.` : 'All labelled.'}
                </div>
              ) : null}
              {sex?.enabled && (
                <button className="btn" style={{ width: 'auto', padding: '8px 14px', marginTop: 10, minHeight: 44 }}
                  onClick={runSexPass} disabled={sexBusy || sex.running}>
                  {sexBusy ? 'Starting…' : sex.running ? 'Labelling…' : 'Label stags, hinds and boar now'}
                </button>
              )}
              {sexMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{sexMsg}</div>}
            </div>
          </SettingsSection>
        )
      })()}

      <SettingsSection id="account" title="Signed in as" defaultOpen>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 14, flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>
            {me?.email ?? '…'}
          </div>
          <button
            onClick={() => {
              if (!confirmSignOut()) return
              signOut()
              nav('/login')
            }}
            style={{ ...smallBtn, padding: '9px 16px', fontSize: 14 }}
          >
            Sign out
          </button>
        </div>
      </SettingsSection>

      {admin && <PhoneProblems />}

      {admin && status && (
        <SettingsSection id="system" title="System" style={{ marginBottom: 0 }}>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{k}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
            </div>
          ))}
          {status.last_sync && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>Last photo fetch</span>
              <span>{FETCH_WORDS[status.last_sync.status] ?? status.last_sync.status}{status.last_sync.at ? `, ${ageLabel(status.last_sync.at)}` : ''}</span>
            </div>
          )}
          {status.disk && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '4px 0' }}
              role={status.disk.low ? 'alert' : undefined} data-disk={status.disk.low ? 'low' : 'ok'}>
              <span style={{ color: 'var(--text-dim)' }}>Space for photos</span>
              <span style={{ textAlign: 'right', color: status.disk.low ? 'var(--skip)' : undefined }}>
                {status.disk.free_gb} GB free{status.disk.low
                  ? '. Nearly full: new photos can’t be saved once it is. Ask whoever runs the server to free some space.' : ''}
              </span>
            </div>
          )}
          {status.suntek && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>Suntek photos</span>
              <span style={{ textAlign: 'right', color: status.suntek.failed ? 'var(--skip)' : undefined }}>
                {status.suntek.ready ?? '?'} waiting{status.suntek.failed
                  ? `. ${status.suntek.failed} failed: ask whoever runs the server to retry them.` : ''}
              </span>
            </div>
          )}
        </SettingsSection>
      )}
    </div>
  )
}
