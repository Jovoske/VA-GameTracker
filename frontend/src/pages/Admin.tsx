import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ageLabel, api, changePassword, noAnswer, peekMe, plainWords, signOut, whoAmI } from '../api'
import { confirmSignOut } from '../sits'
import { useOnServerLanguage } from '../hooks'
import LanguagePicker from '../components/LanguagePicker'
import { type Key, LANGS, fmtDate, fmtList, lasted, t, tOr, tn, useLang } from '../i18n'
import HarvestBook from '../components/HarvestBook'
import NotificationSettings from '../components/NotificationSettings'
import { resetChoices } from '../components/PhotoFix'
import PhoneProblems from '../components/PhoneProblems'
import { BackupRows, type BackupStatus, DiskRow, type Disk, type RestoreCheck, UpdateStatus, type VersionInfo } from '../components/ServerStatus'
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
  // Free space where the photos are kept. Null when unreadable.
  disk?: Disk | null
  // The nightly backup and the weekly restore test; null when never run here.
  backup?: BackupStatus | null
  restore_check?: RestoreCheck | null
}
/** The AI pass (app.ai.checking): its backlog, what it gave up on, why it stopped. */
type AiStatus = {
  waiting: number
  failed: number
  // Photos of the last month whose file never downloaded (older servers leave it out).
  lost?: number
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
type CameraProvider = 'spypoint' | 'ubox' | 'nordic' | 'suntek_email' | 'suntek_ftp'
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
const fetchWords = (status: string) => tOr(`admin.fetch.${status}`, status)
const NUDGE_KEY = 'gs.settings.advice-nudge-done'

/** One short line on the AI pass for the folded section: what matters first. */
function aiSummary(ai: AiStatus): { text: string; warn: boolean } {
  if (ai.stopped) return { text: t('admin.ai.stopped'), warn: true }
  if (ai.failed > 0) return { text: t('admin.ai.failedN', { n: ai.failed }), warn: true }
  if (ai.waiting > 0) return { text: t('admin.ai.waitingN', { n: ai.waiting }), warn: false }
  return { text: t('admin.ai.allChecked'), warn: false }
}
const providerNames: Record<CameraProvider, string> = {
  spypoint: 'SPYPOINT',
  ubox: 'UBox Pro',
  nordic: 'Nordic Gamekeeper',
  suntek_email: 'Suntek · Email',
  suntek_ftp: 'Suntek · FTP / FTPS',
}
const providerName = (provider: CameraProvider | '') => provider ? providerNames[provider] : ''
const emptyCamera = (provider: CameraProvider | '' = '') => ({
  username: '', password: '', label: '', provider, interval: '60', daily: '500',
  host: '', port: provider === 'suntek_email' ? '993' : '21',
  folder: provider === 'suntek_email' ? 'INBOX' : '/', sender: '',
  transport: provider === 'suntek_email' ? 'imap_tls' : 'ftps', timezone: 'Europe/Helsinki',
})
const needsLook = (a: CamAccount) => a.active
  && (a.status.state === 'failing' || a.status.state === 'stale' || a.status.cameras_failing > 0)
/** "3 h", "2 d": how long. */
const forLabel = (iso: string) => lasted(iso)

/** One line on whether the login works, in words: what is wrong comes first. */
function loginLine(a: CamAccount): { text: string; warn: boolean } {
  const s = a.status
  if (!a.active) return { text: t('admin.login.copy'), warn: false }
  if (a.importing) return { text: t('admin.login.importing'), warn: false }
  const where = a.primary && s.password_problem ? ` ${t('admin.login.env')}` : ''
  if ((s.state === 'ok' || s.state === 'busy') && s.cameras_failing > 0) {
    return { text: `${t('admin.login.camerasFailing', { count: s.cameras_failing })} ${s.camera_error ?? ''}`.trim(), warn: true }
  }
  switch (s.state) {
    case 'failing':
      return { text: `${s.error ?? t('admin.login.lastFailed')}${where}`, warn: true }
    case 'stale':
      return {
        text: s.last_ok_at ? t('admin.login.staleFor', { time: forLabel(s.last_ok_at) }) : t('admin.login.staleYet'),
        warn: true,
      }
    case 'busy':
      return { text: t('admin.login.busy'), warn: false }
    case 'ok':
      return { text: t('admin.login.working', { ago: s.last_ok_at ? ageLabel(s.last_ok_at) : t('time.justNow') }), warn: false }
    default:
      return { text: t('admin.login.notYet'), warn: false }
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
      <legend style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{t('admin.limits')}</legend>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        <label htmlFor={`${prefix}-interval`} style={{ flex: '1 1 170px', fontSize: 13 }}>
          {t('admin.minGap')}
          <input id={`${prefix}-interval`} className="input" type="number" inputMode="numeric"
            min={10} max={3600} step={1} required value={limits.interval} style={{ marginTop: 5 }}
            aria-describedby={`${prefix}-help`}
            onChange={(e) => onChange({ ...limits, interval: e.target.value })} />
        </label>
        <label htmlFor={`${prefix}-daily`} style={{ flex: '1 1 170px', fontSize: 13 }}>
          {t('admin.maxDay')}
          <input id={`${prefix}-daily`} className="input" type="number" inputMode="numeric"
            min={1} max={5000} step={1} required value={limits.daily} style={{ marginTop: 5 }}
            aria-describedby={`${prefix}-help`}
            onChange={(e) => onChange({ ...limits, daily: e.target.value })} />
        </label>
      </div>
      <div id={`${prefix}-help`} style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, marginTop: 8 }}>
        {t('admin.limitsHelp')}
      </div>
    </fieldset>
  )
}
// Every button here is a glove's height (44 px): Hide, Remove and Edit limits were
// 27 px, with Hide 10 px from the advice switch (audit D-15, I-16).
const smallBtn = {
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text-dim)',
  borderRadius: 'var(--r-ctl)',
  minHeight: 44,
  padding: '8px 12px',
  fontSize: 13,
  cursor: 'pointer',
  flexShrink: 0,
} as const
// The buttons a hunter needs when a login breaks: the same size, in full colour.
const loginBtn = { ...smallBtn, padding: '8px 14px', color: 'var(--text)' } as const
// The green buttons that aren't full width.
const goBtn = { width: 'auto', padding: '9px 14px', minHeight: 44 } as const

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
    if (clean !== null && !clean) { setErr(t('cameras.typeName')); return }
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
      setErr(x.offline ? t('admin.nameNoSignal') : x.timeout ? t('admin.nameNoAnswer') : t('admin.nameFailed', { why: x.message }))
    } finally {
      setSaving(false)
    }
  }

  const style = { fontSize: 14, color: sp.huntable ? 'var(--text)' : 'var(--text-dim)' }
  if (!canEdit) return <div style={style}>{sp.common_name}</div>
  if (!editing) {
    return (
      <button type="button" className="species-name" style={style} aria-label={t('cameras.renameNamed', { name: sp.common_name })}
        onClick={() => { setDraft(sp.common_name); setErr(''); setEditing(true) }}>
        {sp.common_name}
      </button>
    )
  }
  return (
    <form className="species-name-form" aria-busy={saving} onSubmit={(e) => { e.preventDefault(); void save(draft) }}
      onKeyDown={(e) => { if (e.key === 'Escape' && !saving) { e.preventDefault(); setEditing(false) } }}>
      <label htmlFor={field} className="sr-only">{t('admin.nameFor', { name: sp.common_name })}</label>
      <input id={field} className="input" value={draft} maxLength={40} autoFocus disabled={saving}
        aria-invalid={!!err} onChange={(e) => { setDraft(e.target.value); setErr('') }} />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        <button type="submit" style={loginBtn} disabled={saving}>{saving ? t('common.saving') : t('common.save')}</button>
        <button type="button" style={loginBtn} disabled={saving} onClick={() => setEditing(false)}>{t('common.cancel')}</button>
        {sp.default_name && sp.default_name !== sp.common_name && (
          <button type="button" style={loginBtn} disabled={saving} onClick={() => void save(null)}>
            {t('admin.appName', { name: sp.default_name })}
          </button>
        )}
      </div>
      {err && <p role="alert" style={{ margin: 0, fontSize: 13, color: 'var(--skip)' }}>{err}</p>}
    </form>
  )
}

/** Anything in System the owner should act on: shown beside its heading when folded. */
function systemNeedsLook(s: Status): boolean {
  if (s.disk?.low) return true
  if ('backup' in s && (!s.backup || !s.backup.ok || s.backup.late)) return true
  return !!s.restore_check && !s.restore_check.ok
}

export default function Admin() {
  const nav = useNavigate()
  const lang = useLang()
  const [version, setVersion] = useState<VersionInfo | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [sexMsg, setSexMsg] = useState('')
  const [sexBusy, setSexBusy] = useState(false)
  const [retryBusy, setRetryBusy] = useState(false)
  const [retryMsg, setRetryMsg] = useState('')
  const [nudgeGone, setNudgeGone] = useState(() => {
    try { return localStorage.getItem(NUDGE_KEY) === '1' } catch { return false }
  })
  const [species, setSpecies] = useState<Species[]>([])
  // Whether the list has come: an empty one is "no animals yet", not "Loading…" (D-13).
  const [speciesLoaded, setSpeciesLoaded] = useState(false)
  const [speciesErr, setSpeciesErr] = useState('')
  const [savingId, setSavingId] = useState<string | null>(null)
  const [me, setMe] = useState<Me | null>(() => peekMe())
  const [users, setUsers] = useState<UserRow[]>([])
  const [newUser, setNewUser] = useState({ email: '', password: '', role: 'member' })
  const [userMsg, setUserMsg] = useState('')
  // One add or removal at a time: a second tap on a slow link used to send it twice,
  // and the second answer said it had failed (audit D-24).
  const [userBusy, setUserBusy] = useState(false)
  const [accounts, setAccounts] = useState<CamAccount[]>([])
  const [newAcct, setNewAcct] = useState(emptyCamera)
  const acctSubmitting = useRef(false)
  const inbox = newAcct.provider === 'suntek_email' || newAcct.provider === 'suntek_ftp'
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
  const [pwBusy, setPwBusy] = useState(false)
  // Only an admin changes the animals, the people and the server's own settings; the
  // server refuses anyone else, so nobody else is offered them (audit D-12, I-15).
  const admin = me?.role === 'admin'
  const viewer = me?.role === 'viewer'

  async function runSexPass() {
    setSexBusy(true)
    try {
      const r = await api<{ note?: string }>('/admin/sex-pass', { method: 'POST' })
      setSexMsg(r.note || t('admin.started'))
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
    api<VersionInfo>('/admin/version').then(setVersion).catch(() => {})
    loadStatus()
    api<UserRow[]>('/users').then(setUsers).catch(() => {})
  }, [admin])
  // A language picked above reached the server: the animals' names, the logins'
  // states and the AI's status come again in it.
  useOnServerLanguage(() => {
    loadSpecies()
    api<CamAccount[]>('/camera-accounts').then(setAccounts).catch(() => {})
    if (admin) loadStatus()
  })

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
    api<Species[]>('/species', { timeoutMs: 20_000 })
      .then((list) => { setSpecies(list); setSpeciesLoaded(true) })
      .catch((e) => setSpeciesErr((e as Error).message))
  }

  async function addUser() {
    if (userBusy) return
    setUserBusy(true)
    setUserMsg('')
    const email = newUser.email.trim()
    try {
      await api('/users', { method: 'POST', body: JSON.stringify({ ...newUser, email }), timeoutMs: 20_000 })
      setNewUser({ email: '', password: '', role: 'member' })
      setUserMsg(t('admin.added', { email }))
      setUsers(await api<UserRow[]>('/users'))
    } catch (e) {
      setUserMsg(noAnswer(e) === 'timeout'
        ? t('admin.maybeAdded')
        : t('admin.notAdded', { email, why: (e as Error).message }))
    } finally {
      setUserBusy(false)
    }
  }

  async function delUser(u: UserRow) {
    if (userBusy) return
    if (!window.confirm(t('admin.removeUser', { email: u.email }))) return
    setUserBusy(true)
    setUserMsg('')
    try {
      const r = await api<{ note: string; camera_logins_moved: number }>(`/users/${u.id}`, { method: 'DELETE', timeoutMs: 20_000 })
      setUserMsg(r.note)
      setUsers(await api<UserRow[]>('/users'))
      if (r.camera_logins_moved) setAccounts(await api<CamAccount[]>('/camera-accounts'))
    } catch (e) {
      setUserMsg((e as Error).message)
    } finally {
      setUserBusy(false)
    }
  }

  async function addAccount() {
    if (acctSubmitting.current || !newAcct.provider) return
    acctSubmitting.current = true
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
          ...(newAcct.provider === 'ubox' ? {
            ubox_min_interval_seconds: Number(newAcct.interval),
            ubox_max_images_per_day: Number(newAcct.daily),
          } : {}),
          ...(inbox ? { connection: {
            host: newAcct.host.trim(), port: Number(newAcct.port), folder: newAcct.folder.trim(),
            transport: newAcct.transport, sender: newAcct.sender.trim(), timezone: newAcct.timezone.trim(),
          } } : {}),
        }),
      })
      setNewAcct(emptyCamera())
      setAcctMsg(r.note || t('admin.addedShort'))
      try {
        setAccounts(await api<CamAccount[]>('/camera-accounts'))
      } catch {
        setAcctMsg(`${r.note || t('admin.addedShort')} ${t('cameraSetup.refreshPending')}`)
      }
      followImport()
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
    acctSubmitting.current = false
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
    if (!window.confirm(t('admin.removeLogin', { label: a.label }))) return
    setAcctMsg('')
    try {
      await api(`/camera-accounts/${a.id}`, { method: 'DELETE' })
      setAccounts(await api<CamAccount[]>('/camera-accounts'))
    } catch (e) {
      setAcctMsg((e as Error).message)
    }
  }

  // One change at a time: a second tap used to report "That is not your current
  // password" after the first had changed it (audit D-24).
  async function changePw() {
    if (pwBusy) return
    setPwBusy(true)
    setPwMsg('')
    try {
      const note = await changePassword(pw.current, pw.next)
      setPw({ current: '', next: '' })
      setPwMsg(note)
    } catch (e) {
      setPwMsg(noAnswer(e) === 'timeout'
        ? t('admin.pwMaybe')
        : t('admin.pwNot', { why: (e as Error).message }))
    } finally {
      setPwBusy(false)
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
      setSpeciesErr(t('admin.spNotChanged', { name: s.common_name, why: (e as Error).message }))
    }
    setSavingId(null)
  }

  // Hidden animals (rabbits) leave the whole app: photos, counts, alerts, advice. Asked
  // first: it sits beside the advice switch, and a gloved miss hid an animal for
  // everyone (audit I-16).
  async function hideSpecies(s: Species, hidden: boolean) {
    if (hidden && !window.confirm(t('admin.hideConfirm', { name: s.common_name }))) return
    setSavingId(s.id)
    const before = s
    setSpecies((list) => list.map((x) => (x.id === s.id ? { ...x, hidden, huntable: hidden ? false : x.huntable } : x)))
    setSpeciesErr('')
    try {
      await api(`/species/${s.id}`, { method: 'PATCH', body: JSON.stringify({ hidden }) })
      resetChoices()
    } catch (e) {
      setSpecies((list) => list.map((x) => (x.id === s.id ? before : x)))
      setSpeciesErr(t('admin.spNotChanged', { name: s.common_name, why: (e as Error).message }))
    }
    setSavingId(null)
  }

  const rows: [Key, number][] = status
    ? [
        ['nav.cameras', status.cameras],
        ['nav.photos', status.images],
        ['admin.spotted', status.detections],
        ['admin.emptySkipped', status.empty],
      ]
    : []

  const shown = species.filter((s) => !s.hidden)
  const notGame = shown.filter((s) => s.huntable && s.big_game === false)
  const hiddenOnes = species.filter((s) => s.hidden)
  const onCount = shown.filter((s) => s.huntable).length

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <h1 className="page-title">{t('nav.settings')}</h1>

      <SettingsSection id="language" title={t('lang.title')} summary={LANGS.find((l) => l.code === lang)?.name}>
        <p className="settings-hint">{t('lang.hint')}</p>
        <LanguagePicker />
      </SettingsSection>

      <SettingsSection id="advice" title={t('admin.advice')}
        summary={species.length > 0 ? t('admin.adviceOn', { n: onCount, count: shown.length }) : undefined}>
        {admin || !me ? (
          <p className="settings-hint">{t('admin.adviceHint')}{admin ? ` ${t('admin.adviceRename')}` : ''}</p>
        ) : (
          <p className="settings-hint" data-readonly="advice">{t('admin.adviceReadonly')}</p>
        )}
        {speciesErr && species.length > 0 && <p role="alert" style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--skip)' }}>{speciesErr}</p>}
        {!nudgeGone && admin && notGame.length > 0 && (
          <div className="status-panel" data-nudge style={{ marginBottom: 10 }}>
            {t('admin.nudge', { count: notGame.length, names: fmtList(notGame.map((sp) => sp.common_name)) })}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
              <button type="button" style={loginBtn} disabled={savingId === 'nudge'} onClick={() => adviceGameOnly(notGame)}>
                {savingId === 'nudge' ? t('admin.turningOff') : t('admin.turnOff')}
              </button>
              <button type="button" style={loginBtn} onClick={dismissNudge}>{t('admin.keepThem')}</button>
            </div>
          </div>
        )}
        {species.length === 0 ? (
          speciesErr ? (
            <div role="alert" style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>
              {t('admin.couldntAnimals', { why: speciesErr })}
              <button className="text-action" onClick={loadSpecies}>{t('common.tryAgain')}</button>
            </div>
          ) : speciesLoaded ? (
            <div data-species="none" style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>
              {t('admin.noAnimals')}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--text-dim)', padding: '8px 0' }}>{t('common.loading')}</div>
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
                  {t('alertsSet.sightings', { count: s.detections })}
                </div>
              </div>
              {admin ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                  <button type="button" style={smallBtn} disabled={savingId === s.id}
                    aria-label={t('admin.hideLabel', { name: s.common_name })} onClick={() => hideSpecies(s, true)}>
                    {t('admin.hide')}
                  </button>
                  <Toggle
                    on={s.huntable}
                    disabled={savingId === s.id}
                    onChange={() => toggleSpecies(s)}
                    label={t('admin.inAdviceOf', { name: s.common_name })}
                  />
                </div>
              ) : (
                <span style={{ fontSize: 13, color: s.huntable ? 'var(--text)' : 'var(--text-dim)' }}>
                  {s.huntable ? t('admin.inAdvice') : t('common.off')}
                </span>
              )}
            </div>
          ))
        )}
        {hiddenOnes.length > 0 && (
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 4 }}>{t('admin.hiddenEverywhere')}</div>
            {hiddenOnes.map((s) => (
              <div key={s.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '6px 0' }}>
                <div style={{ fontSize: 14, color: 'var(--text-dim)' }}>{s.common_name}</div>
                {admin && <button type="button" style={smallBtn} disabled={savingId === s.id}
                  aria-label={t('admin.showAgainLabel', { name: s.common_name })} onClick={() => hideSpecies(s, false)}>
                  {t('admin.showAgain')}
                </button>}
              </div>
            ))}
          </div>
        )}
      </SettingsSection>

      <NotificationSettings />

      <SettingsSection id="accounts" title={t('fresh.cameraLogins')}
        summary={accounts.some(needsLook)
          ? <span style={{ color: 'var(--skip)' }}>{t('admin.needAttention', { count: accounts.filter(needsLook).length })}</span>
          : accounts.length > 0 ? t('admin.logins', { count: accounts.length }) : undefined}>
        <p className="settings-hint">{t('admin.loginsHint')}</p>
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
                  {t('animals.cameras', { count: a.cameras })}{a.primary ? ` · ${t('admin.estatesOwn')}` : a.added_by_removed ? '' : a.owner ? ` · ${t('admin.addedBy', { name: a.owner })}` : ''}
                </div>
                {a.added_by_removed && (
                  <div data-removed-owner style={{ fontSize: 12, color: 'var(--sand)', overflowWrap: 'anywhere', marginTop: 2 }}>
                    {a.owner ? t('admin.removedOwnerNow', { name: a.added_by_removed, owner: a.owner }) : t('admin.removedOwner', { name: a.added_by_removed })}
                  </div>
                )}
                <div className="login-status" data-state={a.importing ? 'importing' : a.status.state} role={line.warn ? 'alert' : undefined}
                  style={{ fontSize: 13, lineHeight: 1.45, marginTop: 4, color: line.warn ? 'var(--skip)' : 'var(--text-dim)' }}>
                  {line.text}
                </div>
              </div>
              {a.can_remove && (
                <button type="button" onClick={() => delAccount(a)} style={loginBtn}
                  disabled={limitsBusy} aria-label={t('admin.removeNamed', { name: a.label })}>{t('common.remove')}</button>
              )}
            </div>
            {a.can_edit && !a.primary && a.active && reentering?.id !== a.id && a.status.password_problem && (
              <button type="button" style={{ ...loginBtn, marginTop: 8 }} onClick={() => { setReenterMsg(null); setReentering({ id: a.id, password: '' }) }}
                aria-label={t('admin.reenterLabel', { name: a.label })}>{t('admin.reenter')}</button>
            )}
            {reentering?.id === a.id && (
              <form onSubmit={(e) => { e.preventDefault(); void reenterPassword() }} style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
                <label htmlFor={`reenter-${a.id}`} style={{ fontSize: 13 }}>
                  {t('admin.passwordFor', { provider: providerName(a.provider), user: a.username ?? '' })}
                  <input id={`reenter-${a.id}`} className="input" type="password" required autoFocus value={reentering.password}
                    disabled={reenterBusy} style={{ marginTop: 5 }} autoComplete="new-password"
                    onChange={(e) => setReentering({ id: a.id, password: e.target.value })} />
                </label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button className="btn" type="submit" disabled={reenterBusy || !reentering.password} style={goBtn}>
                    {reenterBusy ? t('admin.checkingWith', { provider: providerName(a.provider) }) : t('admin.savePassword')}
                  </button>
                  <button type="button" style={loginBtn} disabled={reenterBusy} onClick={() => setReentering(null)}>{t('common.cancel')}</button>
                </div>
              </form>
            )}
            {reenterMsg?.id === a.id && <div role="status" style={{ marginTop: 8, fontSize: 13, color: 'var(--text-dim)' }}>{reenterMsg.text}</div>}
            {a.provider === 'ubox' && editingLimits?.id !== a.id && (
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <div style={{ fontSize: 12, color: 'var(--text-dim)', flex: '1 1 200px' }}>
                  {t('admin.perCamera', { s: a.ubox_min_interval_seconds, n: a.ubox_max_images_per_day })}
                </div>
                {a.can_edit && <button type="button" style={smallBtn} disabled={limitsBusy}
                  aria-label={t('admin.editLimitsFor', { name: a.label })}
                  onClick={() => setEditingLimits({
                    id: a.id, interval: String(a.ubox_min_interval_seconds), daily: String(a.ubox_max_images_per_day),
                  })}>{t('admin.editLimits')}</button>}
              </div>
            )}
            {a.provider === 'ubox' && a.last_import && (
              <div style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, marginTop: 8 }}>
                {t('admin.lastImport', {
                  when: a.last_import.at ? ` (${fmtDate(a.last_import.at, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })})` : '',
                  added: a.last_import.downloaded, close: a.last_import.interval_skipped, daily: a.last_import.daily_limit_skipped,
                })}
                {a.last_import.no_image > 0 && ` ${t('admin.noPhotoN', { n: a.last_import.no_image })}`}
                {a.last_import.failed > 0 && ` ${t('admin.failedN', { n: a.last_import.failed })}`}
                {a.last_import.error && a.last_import.error !== a.status.error && <div style={{ marginTop: 4 }}>{t('admin.problem', { why: a.last_import.error })}</div>}
              </div>
            )}
            {a.provider === 'ubox' && editingLimits?.id === a.id && (
              <form onSubmit={(e) => { e.preventDefault(); void saveImportLimits() }} style={{ marginTop: 14 }}>
                <UboxImportFields prefix={`account-${a.id}`} limits={editingLimits} disabled={limitsBusy}
                  onChange={(limits) => setEditingLimits({ id: a.id, ...limits })} />
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button className="btn" type="submit" disabled={limitsBusy} style={goBtn}>
                    {limitsBusy ? t('common.saving') : t('admin.saveLimits')}
                  </button>
                  <button type="button" style={smallBtn} disabled={limitsBusy}
                    onClick={() => setEditingLimits(null)}>{t('common.cancel')}</button>
                </div>
              </form>
            )}
          </div>
          )
        })}
        {viewer ? (
          <p className="settings-hint" style={{ marginTop: 10 }}>{t('admin.membersAdd')}</p>
        ) : (
        <form aria-label={t('cameraSetup.add')} onSubmit={(e) => { e.preventDefault(); void addAccount() }}
          style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
          <h3 style={{ margin: '8px 0 0', fontSize: 16 }}>{t('cameraSetup.add')}</h3>
          <p className="settings-hint" style={{ margin: 0 }}>{t('cameraSetup.chooseHint')}</p>
          <label htmlFor="camera-provider" style={{ fontSize: 13 }}>
            {t('cameraSetup.brand')}
            <select id="camera-provider" className="input" value={newAcct.provider} disabled={acctBusy}
              style={{ marginTop: 5 }}
              onChange={(e) => { setNewAcct(emptyCamera(e.target.value as CameraProvider | '')); setAcctMsg('') }}>
              <option value="">{t('cameraSetup.choose')}</option>
              <option value="spypoint">SPYPOINT</option>
              <option value="ubox">UBox Pro</option>
              <option value="nordic">{t('cameraSetup.nordicLabel')}</option>
              {admin && <option value="suntek_email">{t('cameraSetup.emailOption')}</option>}
              {admin && <option value="suntek_ftp">{t('cameraSetup.ftpOption')}</option>}
            </select>
          </label>
          {!admin && <p className="settings-hint" style={{ margin: 0 }}>{t('cameraSetup.adminInbox')}</p>}
          {newAcct.provider && <>
          {inbox && <>
            <p className="settings-hint" style={{ margin: 0 }}>{t(newAcct.provider === 'suntek_email' ? 'cameraSetup.emailHint' : 'cameraSetup.ftpHint')}</p>
            {newAcct.provider === 'suntek_ftp' && <label htmlFor="camera-transport" style={{ fontSize: 13 }}>
              {t('cameraSetup.transport')}
              <select id="camera-transport" className="input" disabled={acctBusy} value={newAcct.transport}
                style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, transport: e.target.value })}>
                <option value="ftps">{t('cameraSetup.ftpsLabel')}</option>
                <option value="ftp">{t('cameraSetup.ftpLabel')}</option>
              </select>
            </label>}
            {newAcct.transport === 'ftp' && <p className="settings-hint" style={{ margin: 0 }}>{t('cameraSetup.plainFtp')}</p>}
            <label htmlFor="camera-host" style={{ fontSize: 13 }}>{t('cameraSetup.host')}
              <input id="camera-host" className="input" required disabled={acctBusy} value={newAcct.host}
                placeholder={t(newAcct.provider === 'suntek_email' ? 'cameraSetup.mailHost' : 'cameraSetup.ftpHost')}
                autoCapitalize="none" spellCheck={false} style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, host: e.target.value })} />
            </label>
            <label htmlFor="camera-port" style={{ fontSize: 13 }}>{t('cameraSetup.port')}
              <input id="camera-port" className="input" type="number" min="1" max="65535" required disabled={acctBusy}
                value={newAcct.port} style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, port: e.target.value })} />
            </label>
            <label htmlFor="camera-folder" style={{ fontSize: 13 }}>{t('cameraSetup.folder')}
              <input id="camera-folder" className="input" required disabled={acctBusy} value={newAcct.folder}
                style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, folder: e.target.value })} />
            </label>
            {newAcct.provider === 'suntek_email' && <label htmlFor="camera-sender" style={{ fontSize: 13 }}>{t('cameraSetup.sender')}
              <input id="camera-sender" className="input" type="email" disabled={acctBusy} value={newAcct.sender}
                style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, sender: e.target.value })} />
            </label>}
            <label htmlFor="camera-timezone" style={{ fontSize: 13 }}>{t('cameraSetup.timezone')}
              <input id="camera-timezone" className="input" required disabled={acctBusy} value={newAcct.timezone}
                placeholder={t('cameraSetup.timezoneExample')} style={{ marginTop: 5 }} onChange={e => setNewAcct({ ...newAcct, timezone: e.target.value })} />
            </label>
          </>}
          <label htmlFor="camera-email" style={{ fontSize: 13 }}>
            {inbox ? t('cameraSetup.username') : t('admin.providerEmail', { provider: providerName(newAcct.provider) })}
            <input id="camera-email" className="input" type={inbox ? 'text' : 'email'} required value={newAcct.username}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, username: e.target.value })} autoComplete="off" />
          </label>
          <label htmlFor="camera-password" style={{ fontSize: 13 }}>
            {inbox ? t('cameraSetup.password') : t('admin.providerPassword', { provider: providerName(newAcct.provider) })}
            <input id="camera-password" className="input" type="password" required value={newAcct.password}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, password: e.target.value })} autoComplete="new-password" />
          </label>
          <label htmlFor="camera-label" style={{ fontSize: 13 }}>
            {inbox ? t('cameraSetup.cameraName') : t('admin.nameOptional')}
            <input required={inbox} id="camera-label" className="input" placeholder={t('admin.namePlaceholder')} value={newAcct.label}
              disabled={acctBusy} style={{ marginTop: 5 }}
              onChange={(e) => setNewAcct({ ...newAcct, label: e.target.value })} />
          </label>
          {newAcct.provider === 'ubox' && (
            <UboxImportFields prefix="new-account" limits={newAcct} disabled={acctBusy}
              onChange={(limits) => setNewAcct({ ...newAcct, ...limits })} />
          )}
          <button className="btn" type="submit" style={goBtn}
            disabled={acctBusy || !newAcct.username.trim() || !newAcct.password}>
            {acctBusy ? t('admin.checkingWith', { provider: providerName(newAcct.provider) }) : t('cameraSetup.connect')}
          </button>
          </>}
        </form>
        )}
        {acctMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{acctMsg}</div>}
      </SettingsSection>

      {me && !viewer && <HarvestBook admin={admin} />}

      {admin && (
        <SettingsSection id="people" title={t('admin.people')}
          summary={users.length > 0 ? t('admin.peopleN', { count: users.length }) : undefined}>
          <p className="settings-hint">{t('admin.peopleHint')}</p>
          {users.map((u) => (
            <div key={u.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderTop: '1px solid var(--border)' }}>
              <div style={{ flex: 1, minWidth: 0, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {u.email}{u.is_you ? ` ${t('admin.you')}` : ''}
              </div>
              <span style={{ fontSize: 11, color: u.role === 'admin' ? 'var(--sand)' : 'var(--text-dim)', border: '1px solid var(--border)', borderRadius: 'var(--r-ctl)', padding: '1px 7px' }}>
                {tOr(`role.${u.role}`, u.role)}
              </span>
              {!u.is_you && <button onClick={() => delUser(u)} style={smallBtn} disabled={userBusy} aria-label={t('admin.removeNamed', { name: u.email })}>{t('common.remove')}</button>}
            </div>
          ))}
          <form onSubmit={(e) => { e.preventDefault(); void addUser() }} aria-busy={userBusy}
            style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
            <input className="input" placeholder={t('login.email')} aria-label={t('admin.newEmail')} value={newUser.email}
              disabled={userBusy} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} autoComplete="off" />
            <input className="input" placeholder={t('admin.pwPlaceholder')} aria-label={t('admin.newPassword')} value={newUser.password}
              disabled={userBusy} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} autoComplete="new-password" />
            <div style={{ display: 'flex', gap: 8 }}>
              <select className="input" style={{ width: 130, minHeight: 44 }} value={newUser.role} aria-label={t('admin.role')}
                disabled={userBusy} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="member">{t('role.memberCap')}</option>
                <option value="admin">{t('role.adminCap')}</option>
              </select>
              <button className="btn" type="submit" style={goBtn}
                disabled={userBusy || !newUser.email.trim() || newUser.password.length < 8}>
                {userBusy ? t('admin.adding') : t('admin.addPerson')}
              </button>
            </div>
          </form>
          {userMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{userMsg}</div>}
        </SettingsSection>
      )}

      <SettingsSection id="password" title={t('login.password')}>
        <form onSubmit={(e) => { e.preventDefault(); void changePw() }} aria-busy={pwBusy}
          style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input className="input" placeholder={t('admin.currentPw')} aria-label={t('admin.currentPw')} type="password" value={pw.current}
            disabled={pwBusy} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
          <input className="input" placeholder={t('admin.newPwPlaceholder')} aria-label={t('admin.newPw')} type="password" value={pw.next}
            disabled={pwBusy} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
          <button className="btn" type="submit" style={goBtn} disabled={pwBusy || !pw.current || pw.next.length < 8}>
            {pwBusy ? t('admin.changing') : t('admin.changePw')}
          </button>
        </form>
        {pwMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{pwMsg}</div>}
      </SettingsSection>

      {admin && <SettingsSection id="version" title={t('admin.version')}
        summary={version ? (version.deploy?.late || (version.deploy?.failed && version.deploy.failed.commit !== version.deploy.running)
          ? <span style={{ color: 'var(--skip)' }}>{t('admin.needsLook')}</span> : `v${version.version}`) : undefined}>
        <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>GameSense v{version?.version ?? '…'}</div>
        <UpdateStatus info={version} />
      </SettingsSection>}

      {admin && status?.ai && (() => {
        const ai = status.ai
        const sex = status.sex_pass
        const sum = aiSummary(ai)
        return (
          <SettingsSection id="ai" title={t('admin.ai.title')}
            summary={<span style={{ color: sum.warn ? 'var(--skip)' : undefined }}>{sum.text}</span>}>
            {ai.stopped ? (
              <div role="alert" data-ai="stopped" style={{ fontSize: 14, lineHeight: 1.5, color: 'var(--skip)' }}>
                {t('admin.ai.notChecking')} {plainWords(ai.stopped)} {ai.log_file
                  ? tn('admin.ai.showsLog', { file: <span style={{ overflowWrap: 'anywhere' }}>{ai.log_file}</span> })
                  : t('admin.ai.shows')}
              </div>
            ) : ai.waiting > 0 ? (
              <div data-ai="waiting" style={{ fontSize: 14, lineHeight: 1.5 }}>
                {t('admin.ai.waiting', { count: ai.waiting })}{' '}
                {ai.running_since ? t('admin.ai.checkingNow') : t('admin.ai.fewHundred')}
              </div>
            ) : ai.failed === 0 ? (
              <div data-ai="ok" style={{ fontSize: 14, lineHeight: 1.5 }}>
                {ai.last_run_at ? t('admin.ai.everyLast', { ago: ageLabel(ai.last_run_at) }) : t('admin.ai.every')}
              </div>
            ) : null}
            {ai.failed > 0 && (
              // The lead when nothing is waiting: never under "every photo has been checked".
              <div data-ai="failed" style={{ marginTop: ai.stopped || ai.waiting > 0 ? 10 : 0, fontSize: ai.stopped || ai.waiting > 0 ? 13 : 14, lineHeight: 1.5 }}>
                <div>
                  {t('admin.ai.failed', { count: ai.failed })}
                </div>
                <button type="button" style={{ ...loginBtn, marginTop: 8 }} onClick={retryFailed} disabled={retryBusy}>
                  {retryBusy ? t('admin.starting') : t('admin.ai.retry')}
                </button>
              </div>
            )}
            {retryMsg && <div role="status" style={{ marginTop: 8, fontSize: 13, color: 'var(--text-dim)' }}>{retryMsg}</div>}
            {(ai.lost ?? 0) > 0 && (
              <div data-ai="lost" style={{ marginTop: 10, fontSize: 13, lineHeight: 1.5 }}>
                {t('admin.ai.lost', { count: ai.lost ?? 0 })}
              </div>
            )}
            {(ai.stopped || ai.last_error) && (
              <details style={{ marginTop: 10, fontSize: 12, color: 'var(--text-dim)' }}>
                <summary style={{ cursor: 'pointer', minHeight: 44, display: 'flex', alignItems: 'center' }}>
                  {ai.stopped ? t('common.detail') : t('admin.ai.lastProblem')}{ai.last_error_at ? `, ${ageLabel(ai.last_error_at)}` : ''}
                </summary>
                <div style={{ overflowWrap: 'anywhere' }}>{ai.stopped ?? ai.last_error}</div>
              </details>
            )}

            <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: 14, fontWeight: 600 }}>{t('admin.sex.title')}</div>
              <p className="settings-hint" style={{ marginTop: 4 }}>{t('admin.sex.hint')}</p>
              {sex && !sex.enabled ? (
                <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>{t('admin.sex.needsKey')}</div>
              ) : sex?.stopped ? (
                <div role="alert" data-sex="stopped" style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--skip)' }}>
                  {sex.last_run_at ? t('admin.sex.stoppedAgo', { ago: ageLabel(sex.last_run_at), why: sex.stopped }) : t('admin.sex.stopped', { why: sex.stopped })}
                </div>
              ) : sex ? (
                <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>
                  {sex.running ? t('admin.sex.now') : sex.waiting > 0 ? t('admin.sex.toLabel', { count: sex.waiting }) : t('admin.sex.all')}
                </div>
              ) : null}
              {sex?.enabled && (
                <button className="btn" style={{ width: 'auto', padding: '8px 14px', marginTop: 10, minHeight: 44 }}
                  onClick={runSexPass} disabled={sexBusy || sex.running}>
                  {sexBusy ? t('admin.starting') : sex.running ? t('admin.sex.labelling') : t('admin.sex.run')}
                </button>
              )}
              {sexMsg && <div role="status" style={{ marginTop: 10, fontSize: 13, color: 'var(--text-dim)' }}>{sexMsg}</div>}
            </div>
          </SettingsSection>
        )
      })()}

      <SettingsSection id="account" title={t('admin.signedInAs')} defaultOpen>
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
            style={{ ...smallBtn, padding: '9px 16px', fontSize: 14, color: 'var(--text)' }}
          >
            {t('nav.signOut')}
          </button>
        </div>
      </SettingsSection>

      {admin && <PhoneProblems />}

      {admin && status && (
        <SettingsSection id="system" title={t('admin.system')} style={{ marginBottom: 0 }}
          summary={systemNeedsLook(status) ? <span style={{ color: 'var(--skip)' }}>{t('admin.needsLook')}</span> : undefined}>
          {rows.map(([k, v]) => (
            <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{t(k)}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</span>
            </div>
          ))}
          {status.last_sync && (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{t('admin.lastFetch')}</span>
              <span>{fetchWords(status.last_sync.status)}{status.last_sync.at ? `, ${ageLabel(status.last_sync.at)}` : ''}</span>
            </div>
          )}
          {status.disk && <DiskRow disk={status.disk} />}
          {'backup' in status && <BackupRows backup={status.backup ?? null} restore={status.restore_check ?? null} />}
          {status.suntek && (
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-dim)' }}>{t('admin.suntek')}</span>
              <span style={{ textAlign: 'right', color: status.suntek.failed ? 'var(--skip)' : undefined }}>
                {status.suntek.failed
                  ? t('admin.suntekFailed', { n: status.suntek.ready ?? '?', failed: status.suntek.failed })
                  : t('admin.suntekWaiting', { n: status.suntek.ready ?? '?' })}
              </span>
            </div>
          )}
        </SettingsSection>
      )}
    </div>
  )
}
