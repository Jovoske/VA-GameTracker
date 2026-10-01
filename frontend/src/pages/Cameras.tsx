import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { type Failure, type Got, ageLabel, api, getFresh, noAnswerWords, peek, peekMe, plainWords, thumbUrl, whoAmI } from '../api'
import PhotoLightbox, { type LightboxPhoto, morePhotosFailed } from '../components/PhotoLightbox'
import SwitchRow from '../components/SwitchRow'
import { NoteMark } from '../components/WorthALook'
import { useRefetchOnReturn } from '../hooks'
import { fmtNumber, t } from '../i18n'
import { whenSeen } from '../night'
import './cameras.css'

type Health = {
  status: string
  detail: string
  producing: boolean
  credits_left: number | null
  hours_since_report: number | null
  // With status not_syncing: the login that fetches this camera, and what is wrong.
  // `camera`: the login works, only this camera's photos could not be listed.
  login?: { label: string | null; error: string | null; camera?: boolean }
}
/** What /cameras/sync/status says about the latest photo fetch. */
type SyncStatus = {
  status: string
  result?: string
  images_downloaded?: number | null
  started_at?: string | null
  problems?: { label: string; error: string }[]
  // The run's summary; ai_error: why looking for animals in the photos stopped.
  details?: { ai_error?: string | null } | null
}
type SyncLine = { state: 'idle' | 'running' | 'ok' | 'quiet' | 'warn' | 'error'; msg: string; logins?: boolean }
type Camera = {
  id: string
  name: string
  provider_name: string | null
  name_is_custom: boolean
  can_rename: boolean
  battery_pct: number | null
  battery_level: string | null
  signal_pct: number | null
  model: string | null
  image_count: number
  empty_count: number
  /** Checked photos with an animal in them, as the strip and Photos show them. */
  animal_count?: number
  /** Photos the strip shows that the AI hasn't checked yet (often grass). */
  unchecked_count?: number
  last_capture: string | null
  last_report_at: string | null
  photo_count: number | null
  photo_limit: number | null
  plan_name: string | null
  cycle_end: string | null
  sd_used_mb: number | null
  sd_total_mb: number | null
  health: Health | null
  // When an admin retired it (taken down): out of the plan and the numbers.
  retired_at?: string | null
  /** Minutes its photos take to arrive (Suntek, by FTP or email), the middle of the last 50. */
  upload_delay_min?: number | null
}
type Img = {
  id: string
  captured_at: string
  file_url: string | null
  is_empty_frame: boolean | null
  reviewed: boolean
  animal_conf: number | null
  /** Its name as Photos and Animals write it ("Stag", "Sounder"); null while nobody has named it. */
  label: string | null
  species_id?: string | null
  group_size: number | null
  fixed_by?: string | null
  notes_count: number
  // The AI hasn't finished with it: still to be checked, or given up on after failing.
  checking?: 'waiting' | 'failed' | null
}

/** What a photo nobody has named is called: an animal only once the AI has looked,
 *  and "Animal" then, as Photos and the viewer call it (routes_photos._items). */
function unnamed(im: Img): string {
  if (im.checking === 'waiting') return t('cameras.notChecked')
  if (im.checking === 'failed') return t('cameras.couldntCheck')
  return t('lb.animal')
}

/** The photo's name as the server writes it everywhere (routes_photos._items), with
 *  the head count of a group: this page used to make up its own ("Boar ♂"). */
function classLabel(im: Img): string {
  if (!im.label) return ''
  return im.group_size && im.group_size > 1 ? `${im.label} ×${im.group_size}` : im.label
}

function batteryColor(p: number | null): string {
  if (p == null) return 'var(--text-dim)'
  if (p < 25) return 'var(--skip)'
  if (p < 50) return 'var(--marginal)'
  return 'var(--go)'
}
function creditColor(count: number | null, limit: number | null): string {
  if (count == null || limit == null || limit === 0) return 'var(--text-dim)'
  const frac = count / limit
  if (frac >= 1) return 'var(--skip)'
  if (frac >= 0.8) return 'var(--marginal)'
  return 'var(--text-dim)'
}
function timeAgo(ts: string | null): string {
  if (!ts) return t('cameras.never')
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 3600) return t('time.minAgo', { n: fmtNumber(Math.max(1, Math.floor(diff / 60))) })
  if (diff < 86400) return t('cameras.hAgo', { n: fmtNumber(Math.floor(diff / 3600)) })
  return t('cameras.dAgo', { n: fmtNumber(Math.floor(diff / 86400)) })
}
/** "last night", "Tuesday" or "3 Sep": when the camera last spoke to us, by the
 *  estate's nights as Photos and Animals say it (audit C-14). */
const sinceLabel = (ts: string): string => whenSeen(ts)
/** Camera health in words a hunter uses, not a status code. */
function healthWords(c: Camera): { label: string; color: string; ok: boolean } {
  const status = c.health?.status ?? 'ok'
  switch (status) {
    // The camera may be fine; its photos are not reaching us. Settings, not batteries.
    case 'not_syncing':
      return { label: t('cameras.h.notSyncing'), color: 'var(--skip)', ok: false }
    case 'disconnected':
      return { label: t('cameras.h.disconnected'), color: 'var(--text-dim)', ok: false }
    case 'retired':
      return { label: t('cameras.h.retired'), color: 'var(--text-dim)', ok: false }
    // A Suntek sends photos only: a week without one is worth a look, nothing more.
    case 'quiet':
      return {
        label: c.last_report_at ? t('cameras.h.noPhotosSince', { when: sinceLabel(c.last_report_at) }) : t('cameras.h.noPhotosYet'),
        color: 'var(--marginal)', ok: false,
      }
    case 'offline':
      return {
        label: c.last_report_at ? t('cameras.h.quietSince', { when: sinceLabel(c.last_report_at) }) : t('cameras.h.never'),
        color: 'var(--skip)', ok: false,
      }
    case 'out_of_credits':
      return { label: t('cameras.h.credits'), color: 'var(--marginal)', ok: false }
    case 'low_battery':
      return { label: t('cameras.h.battery'), color: 'var(--marginal)', ok: false }
    default:
      return { label: t('cameras.h.ok'), color: 'var(--go)', ok: true }
  }
}

/** The line under a camera that is not working for a reason other than the camera. */
function HealthNote({ c }: { c: Camera }) {
  const h = c.health
  if (h?.status === 'not_syncing') {
    // With an error, the login is the problem; without one, fetching has stopped.
    return (
      <p className="cam-health-note cam-health-note--warn">
        {h.login?.camera
          ? t('cameras.lastFetch', { why: h.login.error ?? '' })
          : h.login?.error
            ? h.login.label ? t('cameras.loginNamed', { label: h.login.label, why: h.login.error }) : t('cameras.login', { why: h.login.error })
            : t('cameras.noFetch')}{' '}
        <Link to="/settings#accounts">{t('fresh.cameraLogins')}</Link>
      </p>
    )
  }
  if (h?.status === 'retired') {
    return <p className="cam-health-note">{t('cameras.retiredNote')}</p>
  }
  if (h?.status === 'disconnected') {
    return <p className="cam-health-note">{t('cameras.disconnectedNote')}</p>
  }
  if (h?.status === 'quiet') {
    return <p className="cam-health-note">{t('cameras.quietNote')}</p>
  }
  return null
}

/** How long a camera's photos take to reach the app, in words. */
function delayWords(min: number): string {
  if (min <= 1) return t('cameras.delayMinute')
  if (min < 90) return t('cameras.delayMin', { n: min })
  return t('cameras.delayH', { n: Math.round(min / 60) })
}

/**
 * Photos an hour late, every time, is a camera clock an hour slow: the import can't
 * tell that from a slow upload, but a camera that sends at once doesn't wait an hour
 * (audit H-17). One ahead is put right on import and said in the health line.
 */
function ClockNote({ c }: { c: Camera }) {
  const d = c.upload_delay_min
  if (d == null || d < 50 || d > 75 || c.health?.status === 'retired') return null
  return <p className="cam-health-note cam-health-note--warn">{t('cameras.clockNote')}</p>
}

/** What a finished fetch came to, count first, then what needs a look. */
function resultLine(s: SyncStatus): SyncLine {
  const line = fetchLine(s)
  const ai = s.details?.ai_error
  if (!ai || line.state === 'error') return line
  // The photos came in, but the animal check did not run: they show as not checked
  // yet. The technical detail (in brackets) is for Settings, not this line.
  const why = plainWords(ai)
  const which = (s.images_downloaded ?? 0) > 0 ? t('cameras.aiThey') : t('cameras.aiPhotos')
  return { ...line, state: 'warn', msg: `${line.msg} ${which} ${why}`.trim() }
}

function fetchLine(s: SyncStatus): SyncLine {
  const n = s.images_downloaded ?? 0
  const photos = n > 0 ? t('cameras.newPhotos', { count: n }) : ''
  const problems = s.problems ?? []
  const issue = problems.length
    ? `${problems[0].label}: ${problems[0].error}${problems.length > 1 ? ` ${t('cameras.andMore', { n: problems.length - 1 })}` : ''}`
    : ''
  switch (s.result ?? s.status) {
    case 'skipped':
      return { state: 'quiet', msg: t('cameras.noLogins'), logins: true }
    case 'ok':
      return n > 0 ? { state: 'ok', msg: photos } : { state: 'quiet', msg: t('cameras.nothingNew') }
    case 'error':
      if (n === 0) return { state: 'error', msg: `${t('cameras.couldntFetch')} ${issue}`.trim(), logins: true }
      break
  }
  return { state: 'warn', msg: `${photos || t('cameras.noNewWorked')} ${issue}`.trim(), logins: !!issue }
}

const wait = (ms: number) => new Promise((res) => setTimeout(res, ms))

/** The viewer, over one camera's strip: it pages on into the strip's older photos. */
type Zoom = { camId: string; start: number }
/** Where a photo is counted on its card: checked with an animal, not checked yet, or empty. */
type Kind = 'animal' | 'unchecked' | 'empty'
const kindOf = (im: Pick<Img, 'is_empty_frame'>): Kind =>
  im.is_empty_frame === true ? 'empty' : im.is_empty_frame === false ? 'animal' : 'unchecked'

/** Why a hide or keep wasn't saved, in words: a reload never helps with no signal. */
function notSaved(e: unknown): string {
  const x = e as Failure
  if (x.offline) return t('cameras.notSavedNoSignal')
  if (x.timeout) return t('cameras.notSavedNoAnswer')
  return t('cameras.notSaved', { why: plainWords(x.message || '') }).trim()
}
type CameraName = Pick<Camera, 'id' | 'name' | 'provider_name' | 'name_is_custom' | 'can_rename'>

function CameraNameEditor({ camera, onSaved, onRemove }: { camera: Camera; onSaved: (value: CameraName) => void; onRemove?: () => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(camera.name)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const renameButton = useRef<HTMLButtonElement>(null)
  const fieldId = `camera-name-${camera.id}`

  function close() {
    setEditing(false)
    setError('')
    requestAnimationFrame(() => renameButton.current?.focus())
  }

  async function save(name: string | null) {
    if (saving) return
    if (name !== null && !name.trim()) {
      setError(t('cameras.typeName'))
      return
    }
    if (name !== null && /[\p{Cc}\p{Cf}]/u.test(name)) {
      setError(t('cameras.hiddenChars'))
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const updated = await api<CameraName>(`/cameras/${camera.id}/name`, {
        method: 'PATCH',
        body: JSON.stringify({ name: name === null ? null : name.trim() }),
      })
      onSaved(updated)
      setMessage(name === null ? t('cameras.ownName', { name: updated.name }) : t('cameras.renamed', { name: updated.name }))
      close()
    } catch (e) {
      const detail = (e as Error).message
      setError(t('cameras.couldntName', { why: detail && !detail.includes('[object Object]') ? detail : t('cameras.tryAgainDot') }))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`camera-name${editing ? ' camera-name--editing' : ''}`}>
      <div className="camera-name-heading">
        <span className="camera-name-title">{camera.name}</span>
        {camera.can_rename && !editing && (
          <button
            ref={renameButton}
            className="camera-name-action"
            type="button"
            aria-label={t('cameras.renameNamed', { name: camera.name })}
            onClick={() => { setDraft(camera.name); setError(''); setMessage(''); setEditing(true) }}
          >
            {t('cameras.rename')}
          </button>
        )}
        {onRemove && !editing && (
          <button
            className="camera-name-action"
            type="button"
            aria-label={t('cameras.removeNamed', { name: camera.name })}
            onClick={onRemove}
          >
            {t('common.remove')}
          </button>
        )}
      </div>
      {editing && (
        <form
          className="camera-name-form"
          aria-label={t('cameras.renameNamed', { name: camera.name })}
          aria-busy={saving}
          onSubmit={(e) => { e.preventDefault(); void save(draft) }}
          onKeyDown={(e) => { if (e.key === 'Escape' && !saving) { e.preventDefault(); close() } }}
        >
          <label htmlFor={fieldId}>{t('cameras.nameLabel')}</label>
          <input
            id={fieldId}
            className="input"
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setError('') }}
            onFocus={(e) => e.currentTarget.select()}
            maxLength={100}
            required
            autoFocus
            disabled={saving}
            aria-invalid={!!error}
            aria-describedby={`${fieldId}-hint${error ? ` ${fieldId}-error` : ''}`}
          />
          <p id={`${fieldId}-hint`} className="camera-name-hint">
            {camera.name_is_custom && camera.provider_name
              ? t('cameras.callsItself', { name: camera.provider_name })
              : t('cameras.nameStays')}
          </p>
          <div className="camera-name-buttons">
            <button className="btn" type="submit" disabled={saving || !draft.trim()}>
              {saving ? t('common.saving') : t('common.save')}
            </button>
            <button className="camera-name-action" type="button" onClick={close} disabled={saving}>{t('common.cancel')}</button>
            {camera.name_is_custom && camera.provider_name && (
              <button className="camera-name-action" type="button" onClick={() => void save(null)} disabled={saving}>
                {t('cameras.useOwnName')}
              </button>
            )}
          </div>
          {error && <p id={`${fieldId}-error`} className="camera-name-error" role="alert">{error}</p>}
        </form>
      )}
      <span className="sr-only" role="status">{message}</span>
    </div>
  )
}

/** Admins: a camera taken down is retired, so the plan stops ranking it on what it
 *  saw before it went in a drawer. Its photos stay; it can come back any time. */
function RetireCamera({ camera, onSaved }: { camera: Camera; onSaved: (retiredAt: string | null) => void }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const retired = !!camera.retired_at

  async function change(next: boolean) {
    if (saving) return
    setSaving(true)
    setError('')
    try {
      const r = await api<{ retired_at: string | null }>(`/cameras/${camera.id}/retired`, {
        method: 'PATCH', body: JSON.stringify({ retired: next }),
      })
      onSaved(r.retired_at)
    } catch (e) {
      setError(t('cameras.couldntSave', { why: (e as Error).message }))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="cam-retire">
      <SwitchRow
        label={t('cameras.retire')}
        note={retired ? t('cameras.retireOn') : t('cameras.retireOff')}
        on={retired}
        disabled={saving}
        words={[t('cameras.h.retired'), t('cameras.inUse')]}
        onChange={(next) => void change(next)}
      />
      {error && <p className="cam-health-note cam-health-note--warn" role="alert">{error}</p>}
    </div>
  )
}

function toPhoto(cam: string, im: Img): LightboxPhoto {
  return {
    id: im.id,
    file_url: im.file_url as string,
    captured_at: im.captured_at,
    camera: cam,
    label: im.is_empty_frame ? t('cameras.noAnimal') : classLabel(im) || unnamed(im),
    notes_count: im.notes_count,
    // Where a hunter finds what the detector missed: a note keeps it (PhotoNotes).
    empty: im.is_empty_frame === true,
    species_id: im.species_id,
    fixed_by: im.fixed_by,
  }
}

/** The one line that matters under the name: what the camera last saw, and when. */
function lastSeenLine(c: Camera, imgs: Img[]): string {
  // A frame the AI hasn't checked (or couldn't) is often grass: not "seen" until checked.
  const latest = imgs.find((im) => im.is_empty_frame !== true && !im.checking)
  if (latest) {
    const what = classLabel(latest) || unnamed(latest)
    return t('cameras.lastSeen', { what, ago: timeAgo(latest.captured_at) })
  }
  if (c.last_capture) return t('cameras.lastPhoto', { ago: timeAgo(c.last_capture) })
  return t('cameras.h.noPhotosYet')
}

const STRIP = 80
// The most one reload asks for (the server's cap): a strip paged further back than
// this starts over at this many.
const STRIP_MAX = 300
const imagesPath = (camId: string, includeEmpty: boolean, after?: Img, limit = STRIP) =>
  `/cameras/${camId}/images?limit=${limit}&include_empty=${includeEmpty}${after
    ? `&before=${encodeURIComponent(after.captured_at)}&before_id=${encodeURIComponent(after.id)}` : ''}`

export default function Cameras() {
  // What this session last saw paints at once; the network replaces it (audit K-08).
  const [cameras, setCameras] = useState<Camera[]>(() => peek<Camera[]>('/cameras')?.data ?? [])
  const [images, setImages] = useState<Record<string, Img[]>>(() => Object.fromEntries(
    cameras.flatMap((c) => { const hit = peek<Img[]>(imagesPath(c.id, false)); return hit ? [[c.id, hit.data]] : [] }),
  ))
  const [showHidden, setShowHidden] = useState<Record<string, boolean>>({})
  const [syncing, setSyncing] = useState(false)
  // What the last check came to, so the line under the button reads as a
  // result and not a running commentary: green when photos came in, amber when
  // some did and a login needs a look, red when nothing could be fetched, quiet
  // otherwise. Good news clears itself after a moment; a problem stays.
  const [sync, setSync] = useState<SyncLine>({ state: 'idle', msg: '' })
  useEffect(() => {
    if (sync.state !== 'ok' && sync.state !== 'quiet') return
    const t = setTimeout(() => setSync({ state: 'idle', msg: '' }), 8000)
    return () => clearTimeout(t)
  }, [sync])
  const [err, setErr] = useState('')
  // The list on screen is what this session saw earlier, because the network didn't answer.
  const [savedCopy, setSavedCopy] = useState<Got<Camera[]> | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionErr, setActionErr] = useState('')
  const [zoom, setZoom] = useState<Zoom | null>(null)
  const zoomRef = useRef(zoom)
  zoomRef.current = zoom
  // Viewers look; only members and admins hide or keep photos (the server refuses them).
  const [writer, setWriter] = useState(() => (peekMe()?.role ?? 'viewer') !== 'viewer')
  useEffect(() => {
    let live = true
    whoAmI().then((me) => { if (live) setWriter(me.role !== 'viewer') }).catch(() => {})
    return () => { live = false }
  }, [])
  // Photos being marked empty/animal, held long enough to leave rather than
  // blink out when the strip reloads underneath them.
  const [flagging, setFlagging] = useState<Set<string>>(new Set())
  // The strip a moment before it changes shape. See toggleHidden.
  const [swapping, setSwapping] = useState<string | null>(null)
  // Only an admin can retire a camera.
  const [admin, setAdmin] = useState(() => peekMe()?.role === 'admin')
  useEffect(() => { whoAmI().then((me) => setAdmin(me.role === 'admin')).catch(() => {}) }, [])
  // Remove asks first; a removed camera is a retired one, so it can come back.
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const [retiring, setRetiring] = useState<string | null>(null)

  async function setRetired(c: Camera, next: boolean) {
    if (retiring) return
    setRetiring(c.id)
    setActionErr('')
    try {
      const r = await api<{ retired_at: string | null }>(`/cameras/${c.id}/retired`, {
        method: 'PATCH', body: JSON.stringify({ retired: next }),
      })
      setCameras((cs) => cs.map((x) => (x.id === c.id ? { ...x, retired_at: r.retired_at } : x)))
      setConfirmRemove(null)
      void loadCameras()
    } catch (e) {
      setActionErr(t('cameras.couldntSave', { why: (e as Error).message }))
    } finally {
      setRetiring(null)
    }
  }

  // Leaving the page drops the lists it was still asking for, so the next tab on a
  // thin link isn't queued behind them.
  const ctl = useRef<AbortController | null>(null)
  const signal = () => {
    if (!ctl.current || ctl.current.signal.aborted) ctl.current = new AbortController()
    return ctl.current.signal
  }

  // The newest request for each camera's strip: an older answer arriving late (a
  // slow first load, then "Show empty photos") must not overwrite it (audit C-16).
  const stripRequest = useRef<Record<string, number>>({})
  // Read when a strip is fetched, not when the fetch was set up: a refetch started
  // before the toggle still asks for what is on screen.
  const hiddenRef = useRef(showHidden)
  hiddenRef.current = showHidden
  // Whether each strip has older photos than it shows ("Show older photos"), and why
  // the last older page didn't come.
  const [older, setOlder] = useState<Record<string, boolean>>({})
  const [olderBusy, setOlderBusy] = useState<string | null>(null)
  const [olderErr, setOlderErr] = useState<Record<string, string>>({})
  const imagesRef = useRef(images)
  imagesRef.current = images

  /** A camera's strip, again. As far back as it had been paged (a hide, a fix or a
   *  return to the app used to drop the older photos shown), or the first page. */
  async function loadImages(camId: string, includeEmpty = !!hiddenRef.current[camId], fresh = false) {
    const id = (stripRequest.current[camId] ?? 0) + 1
    stripRequest.current[camId] = id
    const shown = fresh ? 0 : imagesRef.current[camId]?.length ?? 0
    const limit = Math.min(STRIP_MAX, Math.max(STRIP, shown))
    const { data: imgs } = await getFresh<Img[]>(imagesPath(camId, includeEmpty, undefined, limit), { signal: signal() })
    if (stripRequest.current[camId] !== id) return
    setImages((prev) => ({ ...prev, [camId]: imgs }))
    setOlder((prev) => ({ ...prev, [camId]: imgs.length >= limit }))
  }

  /** The next page of a camera's strip, older than the last photo it shows. */
  async function loadOlder(camId: string) {
    const shown = images[camId]
    const last = shown?.[shown.length - 1]
    if (!last || olderBusy) return
    const id = stripRequest.current[camId] ?? 0
    setOlderBusy(camId)
    setOlderErr((prev) => ({ ...prev, [camId]: '' }))
    try {
      const more = await api<Img[]>(imagesPath(camId, !!hiddenRef.current[camId], last), { signal: signal(), timeoutMs: 20_000 })
      if (stripRequest.current[camId] !== id) return
      setImages((prev) => {
        const have = new Set((prev[camId] ?? []).map((im) => im.id))
        return { ...prev, [camId]: [...(prev[camId] ?? []), ...more.filter((im) => !have.has(im.id))] }
      })
      setOlder((prev) => ({ ...prev, [camId]: more.length >= STRIP }))
    } catch (e) {
      if ((e as Error).name !== 'AbortError' && stripRequest.current[camId] === id) {
        setOlderErr((prev) => ({ ...prev, [camId]: morePhotosFailed(e) }))
      }
    } finally {
      setOlderBusy(null)
    }
  }

  async function loadCameras() {
    setLoading(true)
    try {
      const got = await getFresh<Camera[]>('/cameras', { signal: signal() })
      const cams = got.data
      setCameras(cams)
      setSavedCopy(got.stale ? got : null)
      setErr('')
      await Promise.all(cams.map((c) => loadImages(c.id)))
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCameras()
    return () => ctl.current?.abort()
  }, [])
  // Not with a photo open: the strip it pages through would change under it.
  useRefetchOnReturn(() => { if (!zoomRef.current) void loadCameras() })

  // Showing empties turns the scroll strip into a wrapped grid. A short fade
  // over the reflow hides the jump.
  function toggleHidden(camId: string) {
    const next = !showHidden[camId]
    setSwapping(camId)
    window.setTimeout(() => {
      setShowHidden((p) => ({ ...p, [camId]: next }))
      setOlderErr((prev) => ({ ...prev, [camId]: '' }))
      loadImages(camId, next, true).catch(() => setActionErr(t('cameras.couldntPhotos')))
      requestAnimationFrame(() => setSwapping(null))
    }, 110)
  }

  async function flag(camId: string, im: Img, isEmpty: boolean) {
    const imgId = im.id
    setActionErr('')
    setFlagging((s) => new Set(s).add(imgId))
    try {
      // The photo leaves while the write is in flight, so the strip does not
      // simply re-render minus one frame.
      await Promise.all([
        api(`/images/${imgId}/flag`, {
          method: 'POST',
          body: JSON.stringify({ is_empty: isEmpty }),
          timeoutMs: 20_000,
        }),
        new Promise((res) => setTimeout(res, 180)),
      ])
      // The card's counts follow at once; they used to stay as they were until a reload.
      recount(camId, kindOf(im), isEmpty ? 'empty' : 'animal')
      await loadImages(camId)
    } catch (e) {
      setActionErr(notSaved(e))
    }
    setFlagging((s) => {
      const n = new Set(s)
      n.delete(imgId)
      return n
    })
  }

  /** A photo moved from one count on its card to another. One not checked yet that
   *  is hidden was never one of the animal photos, so that count stays. */
  function recount(camId: string, from: Kind, to: Kind) {
    if (from === to) return
    const key = { animal: 'animal_count', unchecked: 'unchecked_count', empty: 'empty_count' } as const
    setCameras((cs) => cs.map((c) => {
      if (c.id !== camId) return c
      const n: Record<Kind, number> = {
        animal: c.animal_count ?? Math.max(0, c.image_count - c.empty_count),
        unchecked: c.unchecked_count ?? 0,
        empty: c.empty_count,
      }
      return { ...c, [key[from]]: Math.max(0, n[from] - 1), [key[to]]: n[to] + 1 }
    }))
  }

  // Fixes made in the viewer ("Wrong?"): that camera's strip and counts are asked
  // again once the viewer closes, so nothing moves under it while it is open.
  const fixedCams = useRef(new Set<string>())
  function photoFixed(id: string) {
    const camId = Object.keys(images).find((cam) => images[cam].some((im) => im.id === id))
    if (camId) fixedCams.current.add(camId)
  }
  function closeViewer() {
    setZoom(null)
    if (!fixedCams.current.size) return
    fixedCams.current.clear()
    void loadCameras()
  }

  // Ask for a fetch, then follow it to its end: the count as soon as the photos are
  // in, then the result. A check already running (the scheduled one) is followed the
  // same way, and nothing here spins for ever: past ten minutes it says it carries on.
  async function syncNow() {
    setSyncing(true)
    setSync({ state: 'running', msg: t('cameras.asking') })
    // A fetch summary started after this is this check's result; an older one isn't.
    let since = -Infinity
    try {
      const r = await api<{ status: string; since?: string | null; note?: string }>('/cameras/sync', { method: 'POST' })
      if (r.since) since = new Date(r.since).getTime() - 5000
      if (r.status === 'busy') setSync({ state: 'running', msg: t('cameras.already') })
      // Another job (Look for repeats, tonight's plan) holds the fetch up: it runs next.
      if (r.status === 'queued') setSync({ state: 'running', msg: r.note ?? t('cameras.otherJob') })
    } catch (e) {
      setSync({ state: 'error', msg: t('cameras.couldntStart', { why: (e as Error).message }) })
      setSyncing(false)
      return
    }
    const began = Date.now()
    let done = false
    let counted = false
    while (!done && Date.now() - began < 10 * 60_000) {
      await wait(Date.now() - began < 60_000 ? 2500 : 10_000)
      let s: SyncStatus
      try {
        s = await api<SyncStatus>('/cameras/sync/status')
      } catch {
        continue // no signal for a moment: keep following it
      }
      const ours = !s.started_at || new Date(s.started_at).getTime() >= since
      if (s.status === 'running') continue
      if (s.status === 'identifying') {
        if (!ours) continue
        const n = s.images_downloaded ?? 0
        if (n === 0) {
          // Nothing came in to look at: this is the result, whatever else the
          // detector is still working through.
          done = true
          setSync(resultLine(s))
        } else if (!counted) {
          counted = true
          setSync({ state: 'running', msg: t('cameras.lookingIn', { count: n }) })
          void loadCameras()
        }
        continue
      }
      done = true
      setSync(ours ? resultLine(s) : { state: 'quiet', msg: t('cameras.doneChecking') })
    }
    if (!done) setSync({ state: 'quiet', msg: t('cameras.stillGoing') })
    await loadCameras()
    setSyncing(false)
  }

  return (
    <div>
      {/* Title and one quiet button on a row of their own; the result of the
          check gets its own line underneath, where it can be read and coloured. */}
      <div className="cam-head">
        <h1 className="page-title cam-head-title">{t('nav.cameras')}</h1>
        {/* Members and admins can ask; a viewer is told it happens by itself (E-09). */}
        {writer ? (
          <button type="button" className="cam-sync-btn" onClick={syncNow} disabled={syncing} aria-busy={syncing}>
            {syncing ? t('common.checking') : t('cameras.check')}
          </button>
        ) : (
          <span className="cam-sync-note" data-viewer-sync>{t('cameras.every15')}</span>
        )}
      </div>
      <div className={`cam-sync-status cam-sync-status--${sync.state}`} role="status" aria-live="polite">
        {sync.state === 'running' && <span className="cam-sync-spinner" aria-hidden="true" />}
        {sync.state === 'ok' && <span className="cam-sync-glyph" aria-hidden="true">✓</span>}
        {(sync.state === 'error' || sync.state === 'warn') && <span className="cam-sync-glyph" aria-hidden="true">!</span>}
        <span>
          {sync.msg}
          {sync.logins && sync.state !== 'running' && <>{' '}<Link className="cam-sync-link" to="/settings#accounts">{t('fresh.cameraLogins')}</Link></>}
        </span>
      </div>
      {err && (
        <div className="card cam-error">
          {t('cameras.didntLoad', { why: err })}
          <button className="text-action" onClick={loadCameras}>{t('common.tryAgain')}</button>
        </div>
      )}
      {savedCopy && !err && (
        <div className="status-panel" role="status">
          {noAnswerWords(savedCopy.why)} {t('photos.savedCopy', { ago: ageLabel(savedCopy.at) })}
          <button className="text-action" onClick={loadCameras}>{t('common.tryAgain')}</button>
        </div>
      )}
      {actionErr && <div className="status-panel" role="alert">{actionErr}<button className="text-action" onClick={() => { setActionErr(''); loadCameras() }}>{t('common.reload')}</button></div>}
      {loading && cameras.length === 0 && <div className="status-panel" role="status">{t('cameras.loading')}</div>}
      {!loading && !err && cameras.length === 0 && <div className="status-panel"><strong>{t('cameras.noneYet')}</strong><p>{writer ? t('cameras.noneWriter') : t('cameras.noneViewer')}</p><a href="/settings">{t('cameras.openSettings')}</a></div>}

      <div className="cam-list">
        {/* Removed cameras last, one line each, and only for an admin, who can bring
            one back; everyone else no longer sees them. */}
        {[...cameras].sort((a, b) => Number(!!a.retired_at) - Number(!!b.retired_at)).map((c) => {
          if (c.retired_at) {
            if (!admin) return null
            return (
              <div key={c.id} className="card cam-card">
                <div className="cam-card-head">
                  <span className="camera-name-title">{c.name}</span>
                  <button className="camera-name-action" type="button" onClick={() => void setRetired(c, false)} disabled={retiring === c.id}>
                    {t('cameras.bringBack')}
                  </button>
                  <span className="cam-health cam-health--warn" style={{ color: 'var(--text-dim)' }}>
                    <span className="cam-health-dot" style={{ background: 'var(--text-dim)' }} aria-hidden="true" />
                    {t('cameras.h.retired')}
                  </span>
                </div>
              </div>
            )
          }
          const hidden = !!showHidden[c.id]
          const imgs = (images[c.id] || []).filter((im) => im.file_url)
          const health = healthWords(c)
          const animalPhotos = c.animal_count ?? Math.max(0, c.image_count - c.empty_count)
          const unchecked = c.unchecked_count ?? 0
          return (
            <div key={c.id} className="card cam-card">
              <div className="cam-card-head">
                <CameraNameEditor
                  camera={c}
                  onSaved={(updated) => setCameras((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item))}
                  onRemove={admin ? () => setConfirmRemove(c.id) : undefined}
                />
                <span className={`cam-health${health.ok ? '' : ' cam-health--warn'}`} style={{ color: health.color }}>
                  <span className="cam-health-dot" style={{ background: health.color }} aria-hidden="true" />
                  {health.label}
                </span>
              </div>
              {confirmRemove === c.id && (
                <div className="cam-remove-ask" role="alertdialog" aria-label={t('cameras.removeNamed', { name: c.name })}>
                  <span>{t('cameras.removeAsk', { name: c.name })}</span>
                  <button className="btn" type="button" onClick={() => void setRetired(c, true)} disabled={retiring === c.id}>
                    {retiring === c.id ? t('common.saving') : t('common.remove')}
                  </button>
                  <button className="camera-name-action" type="button" onClick={() => setConfirmRemove(null)} disabled={retiring === c.id}>{t('common.cancel')}</button>
                </div>
              )}
              <div className="cam-last-seen">{lastSeenLine(c, imgs)}</div>
              <HealthNote c={c} />
              <ClockNote c={c} />

              <div
                className="cam-strip"
                style={{
                  overflowX: hidden ? 'visible' : 'auto',
                  flexWrap: hidden ? 'wrap' : 'nowrap',
                  opacity: swapping === c.id ? 0 : 1,
                }}
              >
                {imgs.map((im) => {
                  const isEmpty = im.is_empty_frame === true
                  const leaving = flagging.has(im.id)
                  return (
                    <div
                      key={im.id}
                      className="cam-thumb-wrap"
                      style={{
                        opacity: leaving ? 0 : 1,
                        transform: leaving ? 'scale(0.92)' : 'scale(1)',
                      }}
                    >
                      <img
                        className="pressable cam-thumb"
                        role="button"
                        tabIndex={0}
                        aria-label={t('cameras.openPhoto', { name: c.name, what: isEmpty ? t('cameras.noAnimal').toLocaleLowerCase() : (classLabel(im) || unnamed(im)).toLocaleLowerCase() })}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                        src={thumbUrl(im.id)}
                        alt={im.label || t('cameras.trailPhoto')}
                        loading="lazy"
                        onClick={() => setZoom({ camId: c.id, start: imgs.indexOf(im) })}
                        style={{
                          opacity: isEmpty ? 0.4 : 1,
                          border: im.reviewed ? '2px solid var(--teal)' : 'none',
                        }}
                      />
                      <NoteMark count={im.notes_count} />
                      {hidden && writer && (
                        <button
                          className="cam-flag"
                          onClick={() => flag(c.id, im, !isEmpty)}
                          disabled={leaving}
                          aria-label={isEmpty ? t('cameras.keepLabel') : t('cameras.hideLabel')}
                          title={isEmpty ? t('cameras.keepTitle') : t('cameras.hideTitle')}
                          style={{
                            background: isEmpty ? 'var(--go)' : 'rgba(0,0,0,0.6)',
                            color: isEmpty ? '#06210C' : '#fff',
                          }}
                        >
                          {isEmpty ? '+' : '×'}
                        </button>
                      )}
                      {hidden && isEmpty && im.animal_conf != null && im.animal_conf >= 0.05 && (
                        <div className="cam-thumb-tag">{t('cameras.maybe')}</div>
                      )}
                      {!isEmpty && im.label && (
                        <div className="cam-thumb-tag cam-thumb-tag--label">{classLabel(im)}</div>
                      )}
                      {!isEmpty && !im.label && im.checking && (
                        <div className="cam-thumb-tag" data-checking={im.checking}>{unnamed(im)}</div>
                      )}
                    </div>
                  )
                })}
                {imgs.length === 0 && <div className="cam-strip-empty">{images[c.id] == null ? t('photos.loading') : hidden ? t('cameras.noPhotos') : t('photos.none') + (writer ? ` ${t('cameras.tapCheck')}` : '')}</div>}
              </div>
              {olderErr[c.id] && older[c.id] && olderBusy !== c.id && <p className="cam-health-note cam-health-note--warn" role="alert">{olderErr[c.id]}</p>}
              {/* One row for what used to be three stacked 44 px controls. */}
              <div className="cam-foot">
              {older[c.id] && imgs.length > 0 && (
                <button className="cam-empties-toggle" onClick={() => loadOlder(c.id)} disabled={olderBusy === c.id}>
                  {olderBusy === c.id ? t('common.loading') : t('photos.older')}
                </button>
              )}

              {c.empty_count > 0 && (
                <button className="cam-empties-toggle" onClick={() => toggleHidden(c.id)} aria-pressed={hidden}>
                  {hidden ? t('cameras.hideEmpty') : t('cameras.showEmpty', { count: c.empty_count })}
                </button>
              )}

              <details className="cam-details">
                <summary>{t('problems.details')}</summary>
                <dl className="cam-details-list">
                  <div><dt>{t('cameras.battery')}</dt><dd style={{ color: batteryColor(c.battery_pct) }}>{c.battery_pct == null ? t('cameras.unknown') : `${c.battery_pct}%`}</dd></div>
                  <div><dt>{t('cameras.signal')}</dt><dd>{c.signal_pct == null ? t('cameras.unknown') : `${c.signal_pct}%`}</dd></div>
                  <div><dt>{t('cameras.lastCheckIn')}</dt><dd>{timeAgo(c.last_report_at)}</dd></div>
                  {c.photo_limit != null && (
                    <div><dt>{t('cameras.plan')}</dt><dd style={{ color: creditColor(c.photo_count, c.photo_limit) }}>{c.plan_name ? t('cameras.usedPlan', { n: c.photo_count ?? '?', of: c.photo_limit, plan: c.plan_name }) : t('cameras.used', { n: c.photo_count ?? '?', of: c.photo_limit })}</dd></div>
                  )}
                  {c.sd_total_mb ? <div><dt>{t('cameras.sd')}</dt><dd>{t('cameras.sdFull', { pct: Math.round(((c.sd_used_mb ?? 0) / c.sd_total_mb) * 100) })}</dd></div> : null}
                  <div><dt>{t('nav.photos')}</dt><dd>{[t('cameras.withAnimals', { n: animalPhotos }), unchecked > 0 ? t('cameras.uncheckedN', { n: unchecked }) : '', c.empty_count > 0 ? t('cameras.emptyN', { n: c.empty_count }) : ''].filter(Boolean).join(', ')}</dd></div>
                  {c.upload_delay_min != null && <div><dt>{t('cameras.arrive')}</dt><dd>{delayWords(c.upload_delay_min)}</dd></div>}
                  {c.model ? <div><dt>{t('cameras.model')}</dt><dd>{c.model}</dd></div> : null}
                </dl>
                {admin && <RetireCamera camera={c} onSaved={(retiredAt) => { setCameras((cs) => cs.map((x) => (x.id === c.id ? { ...x, retired_at: retiredAt } : x))); void loadCameras() }} />}
              </details>
              </div>
            </div>
          )
        })}
      </div>

      {zoom && <PhotoLightbox photos={(images[zoom.camId] || []).filter((im) => im.file_url)
        .map((im) => toPhoto(cameras.find((c) => c.id === zoom.camId)?.name ?? '', im))}
        start={zoom.start} backLabel={t('cameras.back')} onClose={closeViewer}
        hasMore={!!older[zoom.camId]} onNeedMore={() => void loadOlder(zoom.camId)} moreError={olderErr[zoom.camId]}
        onFixed={photoFixed}
        onNotesChange={(id, n) => setImages((prev) => Object.fromEntries(Object.entries(prev).map(([cam, imgs]) =>
          [cam, imgs.map((im) => (im.id === id ? { ...im, notes_count: n } : im))])))}
        onKept={(id) => {
          // Kept as an animal photo, as its Keep button would: the tile and the count follow.
          const camId = Object.keys(images).find((cam) => images[cam].some((im) => im.id === id))
          const was = camId ? images[camId].find((im) => im.id === id) : undefined
          setImages((prev) => Object.fromEntries(Object.entries(prev).map(([cam, imgs]) =>
            [cam, imgs.map((im) => (im.id === id ? { ...im, is_empty_frame: false, reviewed: true } : im))])))
          if (camId && was) recount(camId, kindOf(was), 'animal')
        }} />}
    </div>
  )
}
