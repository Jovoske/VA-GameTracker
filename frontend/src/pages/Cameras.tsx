import { useEffect, useRef, useState } from 'react'
import { api, imageUrl } from '../api'
import PhotoLightbox, { type LightboxPhoto } from '../components/PhotoLightbox'
import { useRefetchOnReturn } from '../hooks'
import './cameras.css'

type Health = {
  status: string
  detail: string
  producing: boolean
  credits_left: number | null
  hours_since_report: number | null
}
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
  last_capture: string | null
  last_report_at: string | null
  photo_count: number | null
  photo_limit: number | null
  plan_name: string | null
  cycle_end: string | null
  sd_used_mb: number | null
  sd_total_mb: number | null
  health: Health | null
}
type Img = {
  id: string
  captured_at: string
  file_url: string | null
  is_empty_frame: boolean | null
  reviewed: boolean
  animal_conf: number | null
  species: string | null
  group_type: string | null
  group_size: number | null
  sex: string | null
}

// Species + group make-up (+ sex once known) as one short label.
function classLabel(im: Img): string {
  const sp = im.species || ''
  const n = im.group_size || 0
  const sexed = im.sex && im.sex !== 'unknown' ? im.sex : null
  if (sexed && im.group_type === 'solitary') {
    if (sp === 'Red Deer') return sexed === 'male' ? 'Stag' : 'Hind'
    if (sp === 'Wild Boar') return sexed === 'male' ? 'Boar ♂' : 'Sow'
  }
  switch (im.group_type) {
    case 'sow_with_piglets': return `Sow + piglets (${n})`
    case 'sounder': return `Boar sounder (${n})`
    case 'hind_with_calf': return `Hind + calf (${n})`
    case 'herd': return `${sp} herd (${n})`
    case 'group': return `${sp} (${n})`
    default: return sp
  }
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
  if (!ts) return 'never'
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}
/** "yesterday", "Tuesday" or "3 Sep": when the camera last spoke to us. */
function sinceLabel(ts: string): string {
  const d = new Date(ts)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days < 1) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 7) return d.toLocaleDateString(undefined, { weekday: 'long' })
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}
/** Camera health in words a hunter uses, not a status code. */
function healthWords(c: Camera): { label: string; color: string; ok: boolean } {
  const status = c.health?.status ?? 'ok'
  switch (status) {
    case 'offline':
      return {
        label: c.last_report_at ? `Quiet since ${sinceLabel(c.last_report_at)}` : 'Never checked in',
        color: 'var(--skip)', ok: false,
      }
    case 'out_of_credits':
      return { label: 'Out of photo credits', color: 'var(--marginal)', ok: false }
    case 'low_battery':
      return { label: 'Battery low', color: 'var(--marginal)', ok: false }
    default:
      return { label: 'Sending photos', color: 'var(--go)', ok: true }
  }
}

type Zoom = { photos: LightboxPhoto[]; idx: number }
type CameraName = Pick<Camera, 'id' | 'name' | 'provider_name' | 'name_is_custom' | 'can_rename'>

function CameraNameEditor({ camera, onSaved }: { camera: Camera; onSaved: (value: CameraName) => void }) {
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
      setError('Type a name first.')
      return
    }
    if (name !== null && /[\p{Cc}\p{Cf}]/u.test(name)) {
      setError('That name has hidden characters in it. Retype it.')
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
      setMessage(name === null ? `Back to the camera's own name: ${updated.name}.` : `Renamed to ${updated.name}.`)
      close()
    } catch (e) {
      const detail = (e as Error).message
      setError(`Could not save the name. ${detail && !detail.includes('[object Object]') ? detail : 'Try again.'}`)
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
            aria-label={`Rename ${camera.name}`}
            onClick={() => { setDraft(camera.name); setError(''); setMessage(''); setEditing(true) }}
          >
            Rename
          </button>
        )}
      </div>
      {editing && (
        <form
          className="camera-name-form"
          aria-label={`Rename ${camera.name}`}
          aria-busy={saving}
          onSubmit={(e) => { e.preventDefault(); void save(draft) }}
          onKeyDown={(e) => { if (e.key === 'Escape' && !saving) { e.preventDefault(); close() } }}
        >
          <label htmlFor={fieldId}>Camera name</label>
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
              ? `The camera calls itself ${camera.provider_name}. Your name stays after a sync.`
              : 'Your name stays after a sync.'}
          </p>
          <div className="camera-name-buttons">
            <button className="btn" type="submit" disabled={saving || !draft.trim()}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button className="camera-name-action" type="button" onClick={close} disabled={saving}>Cancel</button>
            {camera.name_is_custom && camera.provider_name && (
              <button className="camera-name-action" type="button" onClick={() => void save(null)} disabled={saving}>
                Use camera's name
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

function toPhoto(cam: string, im: Img): LightboxPhoto {
  return {
    id: im.id,
    file_url: im.file_url as string,
    captured_at: im.captured_at,
    camera: cam,
    label: im.is_empty_frame ? 'No animal' : classLabel(im) || 'Unknown animal',
  }
}

/** The one line that matters under the name: what the camera last saw, and when. */
function lastSeenLine(c: Camera, imgs: Img[]): string {
  const latest = imgs.find((im) => im.is_empty_frame !== true)
  if (latest) {
    const what = classLabel(latest) || 'Unknown animal'
    return `Last seen: ${what}, ${timeAgo(latest.captured_at)}`
  }
  if (c.last_capture) return `Last photo ${timeAgo(c.last_capture)}`
  return 'No photos yet'
}

export default function Cameras() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [images, setImages] = useState<Record<string, Img[]>>({})
  const [showHidden, setShowHidden] = useState<Record<string, boolean>>({})
  const [syncing, setSyncing] = useState(false)
  // What the last check came to, so the line under the button reads as a
  // result and not a running commentary: green when photos came in, red when
  // it failed, quiet otherwise. Good news clears itself after a moment.
  const [sync, setSync] = useState<{ state: 'idle' | 'running' | 'ok' | 'quiet' | 'error'; msg: string }>({ state: 'idle', msg: '' })
  useEffect(() => {
    if (sync.state !== 'ok' && sync.state !== 'quiet') return
    const t = setTimeout(() => setSync({ state: 'idle', msg: '' }), 8000)
    return () => clearTimeout(t)
  }, [sync])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionErr, setActionErr] = useState('')
  const [zoom, setZoom] = useState<Zoom | null>(null)
  // Photos being marked empty/animal, held long enough to leave rather than
  // blink out when the strip reloads underneath them.
  const [flagging, setFlagging] = useState<Set<string>>(new Set())
  // The strip a moment before it changes shape. See toggleHidden.
  const [swapping, setSwapping] = useState<string | null>(null)

  async function loadImages(camId: string, includeEmpty: boolean) {
    const imgs = await api<Img[]>(`/cameras/${camId}/images?limit=80&include_empty=${includeEmpty}`)
    setImages((prev) => ({ ...prev, [camId]: imgs }))
  }

  async function loadCameras() {
    setLoading(true)
    try {
      const cams = await api<Camera[]>('/cameras')
      setCameras(cams)
      setErr('')
      await Promise.all(cams.map((c) => loadImages(c.id, !!showHidden[c.id])))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCameras()
  }, [])
  useRefetchOnReturn(loadCameras)

  // Showing empties turns the scroll strip into a wrapped grid. A short fade
  // over the reflow hides the jump.
  function toggleHidden(camId: string) {
    const next = !showHidden[camId]
    setSwapping(camId)
    window.setTimeout(() => {
      setShowHidden((p) => ({ ...p, [camId]: next }))
      loadImages(camId, next).catch(() => setActionErr('Could not load those photos. Try again.'))
      requestAnimationFrame(() => setSwapping(null))
    }, 110)
  }

  async function flag(camId: string, imgId: string, isEmpty: boolean) {
    setActionErr('')
    setFlagging((s) => new Set(s).add(imgId))
    try {
      // The photo leaves while the write is in flight, so the strip does not
      // simply re-render minus one frame.
      await Promise.all([
        api(`/images/${imgId}/flag`, {
          method: 'POST',
          body: JSON.stringify({ is_empty: isEmpty }),
        }),
        new Promise((res) => setTimeout(res, 180)),
      ])
      await loadImages(camId, !!showHidden[camId])
    } catch {
      setActionErr('Could not save that. Reload and try again.')
    }
    setFlagging((s) => {
      const n = new Set(s)
      n.delete(imgId)
      return n
    })
  }

  async function syncNow() {
    setSyncing(true)
    setSync({ state: 'running', msg: 'Asking the cameras for new photos…' })
    try {
      const r = await api<{ status: string; note?: string }>('/cameras/sync', { method: 'POST' })
      if (r.status === 'busy') {
        setSync({ state: 'running', msg: r.note || 'Already checking. New photos show up as they arrive.' })
      } else {
        // Poll the sync log until this run finishes, so the line reports a real result.
        let done = false
        for (let i = 0; i < 24 && !done; i++) {
          await new Promise((res) => setTimeout(res, 2500))
          try {
            const s = await api<{ status: string; images_downloaded?: number }>('/cameras/sync/status')
            if (s.status === 'ok') {
              const n = s.images_downloaded ?? 0
              setSync(n > 0
                ? { state: 'ok', msg: `${n} new photo${n === 1 ? '' : 's'} came in.` }
                : { state: 'quiet', msg: 'Nothing new since last time.' })
              done = true
            } else if (s.status === 'error') {
              setSync({ state: 'error', msg: 'Could not reach the cameras. Check the camera login in Settings.' })
              done = true
            } else {
              setSync({ state: 'running', msg: 'Still checking…' })
            }
          } catch {
            /* transient: keep polling */
          }
        }
        if (!done) setSync({ state: 'quiet', msg: 'Taking a while. Photos show up as they arrive.' })
      }
    } catch (e) {
      setSync({ state: 'error', msg: `Could not start the check. ${(e as Error).message}` })
    }
    await loadCameras()
    setSyncing(false)
  }

  return (
    <div>
      {/* Title and one quiet button on a row of their own; the result of the
          check gets its own line underneath, where it can be read and coloured. */}
      <div className="cam-head">
        <h1 className="page-title cam-head-title">Cameras</h1>
        <button type="button" className="cam-sync-btn" onClick={syncNow} disabled={syncing} aria-busy={syncing}>
          {syncing ? 'Checking…' : 'Check for new photos'}
        </button>
      </div>
      <div className={`cam-sync-status cam-sync-status--${sync.state}`} role="status" aria-live="polite">
        {sync.state === 'running' && <span className="cam-sync-spinner" aria-hidden="true" />}
        {sync.state === 'ok' && <span className="cam-sync-glyph" aria-hidden="true">✓</span>}
        {sync.state === 'error' && <span className="cam-sync-glyph" aria-hidden="true">!</span>}
        <span>{sync.msg}</span>
      </div>
      {err && (
        <div className="card cam-error">
          Cameras did not load. {err}
          <button className="text-action" onClick={loadCameras}>Try again</button>
        </div>
      )}
      {actionErr && <div className="status-panel" role="alert">{actionErr}<button className="text-action" onClick={() => { setActionErr(''); loadCameras() }}>Reload</button></div>}
      {loading && cameras.length === 0 && <div className="status-panel" role="status">Loading cameras…</div>}
      {!loading && !err && cameras.length === 0 && <div className="status-panel"><strong>No cameras yet</strong><p>Add your camera login in Settings, then tap Check for new photos.</p><a href="/settings">Open Settings</a></div>}

      <div className="cam-list">
        {cameras.map((c) => {
          const hidden = !!showHidden[c.id]
          const imgs = (images[c.id] || []).filter((im) => im.file_url)
          const health = healthWords(c)
          const animalPhotos = Math.max(0, c.image_count - c.empty_count)
          return (
            <div key={c.id} className="card cam-card">
              <div className="cam-card-head">
                <CameraNameEditor camera={c} onSaved={(updated) => setCameras((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item))} />
                <span className={`cam-health${health.ok ? '' : ' cam-health--warn'}`} style={{ color: health.color }}>
                  <span className="cam-health-dot" style={{ background: health.color }} aria-hidden="true" />
                  {health.label}
                </span>
              </div>
              <div className="cam-last-seen">{lastSeenLine(c, imgs)}</div>

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
                        aria-label={`Open photo from ${c.name}: ${isEmpty ? 'no animal' : classLabel(im) || 'unknown animal'}`}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                        src={imageUrl(im.file_url as string)}
                        alt={im.species || 'trail-camera photo'}
                        loading="lazy"
                        onClick={() => {
                          setZoom({ photos: imgs.map((x) => toPhoto(c.name, x)), idx: imgs.indexOf(im) })
                        }}
                        style={{
                          opacity: isEmpty ? 0.4 : 1,
                          border: im.reviewed ? '2px solid var(--teal)' : 'none',
                        }}
                      />
                      {hidden && (
                        <button
                          className="cam-flag"
                          onClick={() => flag(c.id, im.id, !isEmpty)}
                          disabled={leaving}
                          aria-label={isEmpty ? 'Keep this photo: there is an animal in it' : 'Hide this photo: nothing in it'}
                          title={isEmpty ? 'Keep (animal)' : 'Hide (empty)'}
                          style={{
                            background: isEmpty ? 'var(--go)' : 'rgba(0,0,0,0.6)',
                            color: isEmpty ? '#06210C' : '#fff',
                          }}
                        >
                          {isEmpty ? '+' : '×'}
                        </button>
                      )}
                      {hidden && isEmpty && im.animal_conf != null && im.animal_conf >= 0.05 && (
                        <div className="cam-thumb-tag">Maybe</div>
                      )}
                      {!isEmpty && im.species && (
                        <div className="cam-thumb-tag cam-thumb-tag--label">{classLabel(im)}</div>
                      )}
                    </div>
                  )
                })}
                {imgs.length === 0 && <div className="cam-strip-empty">{images[c.id] == null ? 'Loading photos…' : hidden ? 'No photos yet.' : 'No animal photos yet. Tap Check for new photos.'}</div>}
              </div>

              {c.empty_count > 0 && (
                <button className="cam-empties-toggle" onClick={() => toggleHidden(c.id)} aria-pressed={hidden}>
                  {hidden ? 'Hide empty photos' : `Show ${c.empty_count} empty photo${c.empty_count === 1 ? '' : 's'}`}
                </button>
              )}

              <details className="cam-details">
                <summary>Details</summary>
                <dl className="cam-details-list">
                  <div><dt>Battery</dt><dd style={{ color: batteryColor(c.battery_pct) }}>{c.battery_pct == null ? 'Unknown' : `${c.battery_pct}%`}</dd></div>
                  <div><dt>Signal</dt><dd>{c.signal_pct == null ? 'Unknown' : `${c.signal_pct}%`}</dd></div>
                  <div><dt>Last check-in</dt><dd>{timeAgo(c.last_report_at)}</dd></div>
                  {c.photo_limit != null && (
                    <div><dt>Photo plan</dt><dd style={{ color: creditColor(c.photo_count, c.photo_limit) }}>{c.photo_count ?? '?'} of {c.photo_limit} used{c.plan_name ? ` (${c.plan_name})` : ''}</dd></div>
                  )}
                  {c.sd_total_mb ? <div><dt>SD card</dt><dd>{Math.round(((c.sd_used_mb ?? 0) / c.sd_total_mb) * 100)}% full</dd></div> : null}
                  <div><dt>Photos</dt><dd>{animalPhotos} with animals{c.empty_count > 0 ? `, ${c.empty_count} empty` : ''}</dd></div>
                  {c.model ? <div><dt>Model</dt><dd>{c.model}</dd></div> : null}
                </dl>
              </details>
            </div>
          )
        })}
      </div>

      {zoom && <PhotoLightbox photos={zoom.photos} start={zoom.idx} backLabel="Back to cameras" onClose={() => setZoom(null)} />}
    </div>
  )
}
