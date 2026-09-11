import { DownloadSimpleIcon } from '@phosphor-icons/react/dist/csr/DownloadSimple'
import { MagnifyingGlassMinusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassMinus'
import { MagnifyingGlassPlusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassPlus'
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { api, imageUrl } from '../api'
import Overlay from '../components/Overlay'
import { useReducedMotion, useRefetchOnReturn } from '../hooks'

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

// Compose species + group composition (+ sex once the vision pass has run) into one label.
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
function healthMeta(status: string): { label: string; color: string } {
  switch (status) {
    case 'offline':
      return { label: 'OFFLINE', color: 'var(--skip)' }
    case 'out_of_credits':
      return { label: 'NO CREDITS', color: 'var(--marginal)' }
    case 'low_battery':
      return { label: 'LOW BATTERY', color: 'var(--marginal)' }
    default:
      return { label: 'OK', color: 'var(--go)' }
  }
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
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

type Zoom = { list: Img[]; idx: number; cam: string }

/**
 * Where the photo sits on the stage: scale, and offset from centre in px.
 * `snap` is true for a jump the user asked for (double-tap, button, key) and
 * false while a finger is driving it — one animates, the other must not lag.
 */
type View = { s: number; x: number; y: number; snap: boolean }
const FIT: View = { s: 1, x: 0, y: 0, snap: true }
const MAX_ZOOM = 6
const TAP_ZOOM = 2.5
type Pt = { x: number; y: number }
const dist = (a: Pt, b: Pt) => Math.hypot(a.x - b.x, a.y - b.y)
const mid = (a: Pt, b: Pt): Pt => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })

/** `PL19_2026-09-04_22-05.jpg`: the camera and the moment, in local time. */
function downloadName(cam: string, capturedAt: string): string {
  const d = new Date(capturedAt)
  const p = (n: number) => String(n).padStart(2, '0')
  const stem = cam.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'camera'
  return `${stem}_${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}_${p(d.getHours())}-${p(d.getMinutes())}.jpg`
}

export default function Cameras() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [images, setImages] = useState<Record<string, Img[]>>({})
  const [showHidden, setShowHidden] = useState<Record<string, boolean>>({})
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [actionErr, setActionErr] = useState('')
  const [imgError, setImgError] = useState(false)
  const [zoom, setZoom] = useState<Zoom | null>(null)
  // Photos being marked empty/animal, held long enough to leave rather than
  // blink out when the strip reloads underneath them.
  const [flagging, setFlagging] = useState<Set<string>>(new Set())
  // The strip a moment before it changes shape. See toggleHidden.
  const [swapping, setSwapping] = useState<string | null>(null)
  const [imgReady, setImgReady] = useState(true)
  const swipe = useRef<{ x: number; t: number } | null>(null)
  const reduced = useReducedMotion()
  const [view, setView] = useState<View>(FIT)
  const viewRef = useRef(view)
  viewRef.current = view
  const [saving, setSaving] = useState(false)
  const stageRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  // Every finger currently on the stage, by pointer id.
  const pointers = useRef(new Map<number, Pt>())
  // q0: the photo point (fit-scale px from its centre) that was under the fingers' midpoint.
  const pinch = useRef<{ d0: number; q0: Pt; s0: number } | null>(null)
  const pan = useRef<{ x: number; y: number; v0: View; moved: boolean } | null>(null)
  const lastTap = useRef<{ t: number; x: number; y: number } | null>(null)

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

  // Lightbox keyboard navigation: ← → to move, + − 0 to zoom. Escape belongs to
  // Overlay now, so that every panel in the app answers it rather than only this one.
  useEffect(() => {
    if (!zoom) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') step(-1)
      if (e.key === 'ArrowRight') step(1)
      if (e.key === '+' || e.key === '=') setView((v) => zoomAt(v.s * 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '-') setView((v) => zoomAt(v.s / 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '0') setView(FIT)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom])

  // Wheel zoom wants preventDefault (ctrl+wheel would otherwise zoom the whole
  // page), and React registers wheel as passive, so this one is bound by hand.
  useEffect(() => {
    const st = stageRef.current
    if (!zoom || !st) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = viewRef.current
      // A trackpad pinch arrives as ctrl+wheel in small deltas, a mouse wheel in
      // big steps; exp() makes both feel proportional.
      setView(zoomAt(v.s * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), local(e.clientX, e.clientY), v, false))
    }
    st.addEventListener('wheel', onWheel, { passive: false })
    return () => st.removeEventListener('wheel', onWheel)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom])

  /** Move through the open camera's photos, stopping at both ends. */
  function step(d: number) {
    if (!zoom) return
    const i = zoom.idx + d
    if (i < 0 || i >= zoom.list.length) return
    // The next photo fades in once it has actually decoded. Swapping src alone
    // gave a blank frame and then a jump as the stage resized to fit it.
    setImgReady(false)
    setView(FIT)
    setImgError(false)
    setZoom({ ...zoom, idx: i })
  }

  /** A pointer position in stage-centre coordinates, which is where the photo's transform is anchored. */
  function local(clientX: number, clientY: number): Pt {
    const r = stageRef.current?.getBoundingClientRect()
    if (!r) return { x: 0, y: 0 }
    return { x: clientX - (r.left + r.width / 2), y: clientY - (r.top + r.height / 2) }
  }

  /** Keep the photo on the stage: it may only slide as far as it overflows, and at fit it stays centred. */
  function clampView(v: View): View {
    const s = Math.min(MAX_ZOOM, Math.max(1, v.s))
    const st = stageRef.current
    const im = imgRef.current
    if (!st || !im) return { ...v, s }
    const ox = Math.max(0, (im.offsetWidth * s - st.clientWidth) / 2)
    const oy = Math.max(0, (im.offsetHeight * s - st.clientHeight) / 2)
    return { ...v, s, x: Math.min(ox, Math.max(-ox, v.x)), y: Math.min(oy, Math.max(-oy, v.y)) }
  }

  /** Put photo point `q` (fit-scale px from its centre) under stage point `m`, at scale `s`. */
  function place(s: number, q: Pt, m: Pt, snap: boolean): View {
    s = Math.min(MAX_ZOOM, Math.max(1, s))
    return clampView({ s, x: m.x - s * q.x, y: m.y - s * q.y, snap })
  }

  /** Rescale so the bit of photo under `p` stays put. */
  function zoomAt(s: number, p: Pt, from: View, snap: boolean): View {
    return place(s, { x: (p.x - from.x) / from.s, y: (p.y - from.y) / from.s }, p, snap)
  }

  /**
   * Swipe to turn the page — on a phone this is the whole navigation, and two
   * 46px arrows were standing in for it. A flick counts even when it barely
   * moves: past 0.11 px/ms the intent is unambiguous, which is the same
   * threshold a drag-to-dismiss uses.
   *
   * Once zoomed in, the same finger pans the photo instead, and two fingers
   * pinch. A double-tap toggles between fit and a close look at that spot.
   */
  function pointerDown(e: ReactPointerEvent<HTMLDivElement>) {
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      /* pointer already gone */
    }
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const v = viewRef.current
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()]
      const m = local(mid(a, b).x, mid(a, b).y)
      pinch.current = { d0: Math.max(1, dist(a, b)), q0: { x: (m.x - v.x) / v.s, y: (m.y - v.y) / v.s }, s0: v.s }
      pan.current = null
      swipe.current = null
    } else if (pointers.current.size === 1) {
      pan.current = { x: e.clientX, y: e.clientY, v0: v, moved: false }
      swipe.current = { x: e.clientX, t: e.timeStamp }
    }
  }

  function pointerMove(e: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(e.pointerId)) return
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
    const g = pinch.current
    if (g && pointers.current.size >= 2) {
      const [a, b] = [...pointers.current.values()]
      const m = mid(a, b)
      setView(place(g.s0 * (dist(a, b) / g.d0), g.q0, local(m.x, m.y), false))
      return
    }
    const p = pan.current
    if (p && viewRef.current.s > 1) {
      const dx = e.clientX - p.x
      const dy = e.clientY - p.y
      if (Math.abs(dx) + Math.abs(dy) > 4) p.moved = true
      setView(clampView({ ...p.v0, x: p.v0.x + dx, y: p.v0.y + dy, snap: false }))
    }
  }

  function pointerUp(e: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(e.pointerId)
    if (pinch.current) {
      if (pointers.current.size >= 2) return
      pinch.current = null
      // Let go with barely any zoom left and it means "back to fit".
      const v = viewRef.current.s < 1.05 ? FIT : viewRef.current
      setView(v)
      // A finger still down carries on as a pan from where it is now.
      const [rest] = [...pointers.current.values()]
      pan.current = rest ? { x: rest.x, y: rest.y, v0: v, moved: true } : null
      swipe.current = null
      return
    }
    const p = pan.current
    pan.current = null
    if (viewRef.current.s > 1) {
      if (p && !p.moved) tap(e)
      return
    }
    const s = swipe.current
    swipe.current = null
    if (!s) return
    const dx = e.clientX - s.x
    const dt = Math.max(1, e.timeStamp - s.t)
    if (Math.abs(dx) < 12) {
      tap(e)
      return
    }
    if (Math.abs(dx) > 60 || Math.abs(dx) / dt > 0.11) step(dx < 0 ? 1 : -1)
  }

  function pointerCancel(e: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(e.pointerId)
    if (pointers.current.size < 2) pinch.current = null
    if (pointers.current.size === 0) {
      pan.current = null
      swipe.current = null
    }
  }

  /** Two taps on the same spot within a third of a second: zoom in there, or back out. */
  function tap(e: ReactPointerEvent<HTMLDivElement>) {
    const l = lastTap.current
    if (l && e.timeStamp - l.t < 320 && Math.hypot(e.clientX - l.x, e.clientY - l.y) < 24) {
      lastTap.current = null
      const v = viewRef.current
      setView(v.s > 1 ? FIT : zoomAt(TAP_ZOOM, local(e.clientX, e.clientY), v, true))
      return
    }
    lastTap.current = { t: e.timeStamp, x: e.clientX, y: e.clientY }
  }

  function toggleZoom() {
    const v = viewRef.current
    setView(v.s > 1 ? FIT : zoomAt(TAP_ZOOM, { x: 0, y: 0 }, v, true))
  }

  async function download(im: Img) {
    if (!zoom || saving) return
    const src = imageUrl(im.file_url as string)
    const name = downloadName(zoom.cam, im.captured_at)
    setSaving(true)
    try {
      // On a phone the share sheet is where "Save Image" lives; a download link
      // on iOS opens the photo in a tab the user then has to find a way out of.
      if (navigator.share && navigator.canShare && window.matchMedia('(pointer: coarse)').matches) {
        try {
          const blob = await (await fetch(src)).blob()
          const file = new File([blob], name, { type: 'image/jpeg' })
          if (navigator.canShare({ files: [file] })) {
            await navigator.share({ files: [file], title: name })
            return
          }
        } catch (e) {
          if ((e as Error).name === 'AbortError') return // sheet dismissed: not an error
        }
      }
      // Everywhere else: the server marks it as an attachment and names it.
      const a = document.createElement('a')
      a.href = `${src}${src.includes('?') ? '&' : '?'}download=1`
      a.download = name
      document.body.appendChild(a)
      a.click()
      a.remove()
    } finally {
      setSaving(false)
    }
  }

  // Reviewing empties turns a horizontal scroll strip into a wrapped grid — the
  // photos stay the same but the shape of the block does not, and snapping
  // between the two reads as the page breaking. A short fade over the reflow
  // hides the double-exposure; the layout changes while nothing is on screen.
  function toggleHidden(camId: string) {
    const next = !showHidden[camId]
    setSwapping(camId)
    window.setTimeout(() => {
      setShowHidden((p) => ({ ...p, [camId]: next }))
      loadImages(camId, next).catch(() => setActionErr('Could not load these photos. Try changing the filter again.'))
      requestAnimationFrame(() => setSwapping(null))
    }, 110)
  }

  async function flag(camId: string, imgId: string, isEmpty: boolean) {
    setActionErr('')
    setFlagging((s) => new Set(s).add(imgId))
    try {
      // The photo leaves while the write is in flight, so the strip does not
      // simply re-render minus one frame with no account of where it went.
      await Promise.all([
        api(`/images/${imgId}/flag`, {
          method: 'POST',
          body: JSON.stringify({ is_empty: isEmpty }),
        }),
        new Promise((res) => setTimeout(res, 180)),
      ])
      await loadImages(camId, !!showHidden[camId])
    } catch {
      setActionErr('Could not save the photo review or refresh the list. Reload the cameras to check its status before trying again.')
    }
    setFlagging((s) => {
      const n = new Set(s)
      n.delete(imgId)
      return n
    })
  }

  async function syncNow() {
    setSyncing(true)
    setSyncMsg('Contacting SPYPOINT…')
    try {
      const r = await api<{ status: string; note?: string }>('/cameras/sync', { method: 'POST' })
      if (r.status === 'busy') {
        setSyncMsg(r.note || 'A sync is already running.')
      } else {
        // Poll the sync log until this run finishes, so the button reports a real result.
        let done = false
        for (let i = 0; i < 24 && !done; i++) {
          await new Promise((res) => setTimeout(res, 2500))
          try {
            const s = await api<{ status: string; images_downloaded?: number }>('/cameras/sync/status')
            if (s.status === 'ok') {
              const n = s.images_downloaded ?? 0
              setSyncMsg(n > 0 ? `Done. ${n} new photo${n === 1 ? '' : 's'}.` : 'Done. No new photos.')
              done = true
            } else if (s.status === 'error') {
              setSyncMsg('Sync failed. See Settings for details.')
              done = true
            } else {
              setSyncMsg('Syncing…')
            }
          } catch {
            /* transient — keep polling */
          }
        }
        if (!done) setSyncMsg('Still running in the background. Photos will appear as they arrive.')
      }
    } catch (e) {
      setSyncMsg((e as Error).message)
    }
    await loadCameras()
    setSyncing(false)
  }

  return (
    <div>
      {/* No wrap and a message slot that is always there: the status text used to
          appear mid-sync and shove the button it was reporting on out of reach. */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12, gap: 10 }}>
        <div style={{ fontSize: 18, fontWeight: 700, flexShrink: 0 }}>Cameras</div>
        <span
          style={{
            fontSize: 12,
            color: 'var(--text-dim)',
            flex: 1,
            minWidth: 0,
            opacity: syncMsg ? 1 : 0,
            transition: 'opacity var(--d-fast) var(--ease-out)',
          }}
        >
          {syncMsg}
        </span>
        <button
          className="btn"
          style={{ width: 'auto', padding: '8px 14px', flexShrink: 0 }}
          onClick={syncNow}
          disabled={syncing}
        >
          {/* A SPYPOINT sync can run for a minute. A label alone leaves the user
              deciding whether a dead button or a slow camera network is to blame. */}
          {syncing && <span className="btn-progress" aria-hidden="true" />}
          <span style={{ position: 'relative' }}>{syncing ? 'Syncing…' : 'Sync now'}</span>
        </button>
      </div>
      {err && (
        <div className="card" style={{ padding: 12, marginBottom: 12, fontSize: 13, color: 'var(--skip)' }}>
          Could not load cameras: {err}
          <button className="text-action" onClick={loadCameras}>Retry loading cameras</button>
        </div>
      )}
      <p className="page-intro">Check camera health and browse the latest 80 photos per camera. Open a photo to view details or review photos with no animal detected.</p>
      <div role="status" className="sr-only">{syncMsg}</div>
      {actionErr && <div className="status-panel" role="alert">{actionErr}<button className="text-action" onClick={() => { setActionErr(''); loadCameras() }}>Reload cameras</button></div>}
      {loading && cameras.length === 0 && <div className="status-panel" role="status">Loading cameras and photos…</div>}
      {!loading && !err && cameras.length === 0 && <div className="status-panel"><strong>No cameras connected yet</strong><p>Connect your SPYPOINT account in Settings, then choose Sync now to import your cameras and photos.</p><a href="/settings">Open Settings →</a></div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {cameras.map((c) => {
          const hidden = !!showHidden[c.id]
          const imgs = (images[c.id] || []).filter((im) => im.file_url)
          return (
            <div key={c.id} className="card" style={{ padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{c.model}</div>
                {c.health && c.health.status !== 'ok' && (
                  <span
                    style={{
                      fontSize: 10, fontWeight: 700, letterSpacing: '.04em', color: '#06210C',
                      background: healthMeta(c.health.status).color, borderRadius: 'var(--r-chip)', padding: '2px 7px',
                    }}
                  >
                    {healthMeta(c.health.status).label}
                  </span>
                )}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ color: batteryColor(c.battery_pct) }}>Battery {c.battery_pct == null ? 'unknown' : `${c.battery_pct}%`}</span>
                  <span style={{ color: 'var(--text-dim)' }}>Signal {c.signal_pct == null ? 'unknown' : `${c.signal_pct}%`}</span>
                  {c.photo_limit != null && (
                    <span style={{ color: creditColor(c.photo_count, c.photo_limit) }}>
                      Plan usage: {c.photo_count ?? '?'}/{c.photo_limit} photos
                    </span>
                  )}
                  <span style={{ color: 'var(--text-dim)' }}>
                    {Math.max(0, c.image_count - c.empty_count)} photos not marked empty · Latest photo: {timeAgo(c.last_capture)}
                  </span>
                </div>
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 5, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span>checked in {timeAgo(c.last_report_at)}</span>
                {c.sd_total_mb ? <span>SD {Math.round(((c.sd_used_mb ?? 0) / c.sd_total_mb) * 100)}% used</span> : null}
                {c.plan_name ? <span>{c.plan_name} plan</span> : null}
                {c.health && c.health.status !== 'ok' ? (
                  <span style={{ color: healthMeta(c.health.status).color }}>{c.health.detail}</span>
                ) : null}
              </div>

              {c.empty_count > 0 && (
                <button
                  onClick={() => toggleHidden(c.id)}
                  style={{
                    marginTop: 10,
                    background: hidden ? 'var(--surface-2)' : 'none',
                    border: '1px solid var(--border)',
                    color: 'var(--text-dim)',
                    borderRadius: 'var(--r-ctl)',
                    padding: '4px 10px',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  {hidden ? 'Hide photos with no animal detected' : `Review ${c.empty_count} photos marked empty`}
                </button>
              )}

              <div
                style={{
                  display: 'flex',
                  gap: 6,
                  marginTop: 10,
                  overflowX: hidden ? 'visible' : 'auto',
                  flexWrap: hidden ? 'wrap' : 'nowrap',
                  opacity: swapping === c.id ? 0 : 1,
                  transition: 'opacity 110ms var(--ease-out)',
                }}
              >
                {imgs.map((im) => {
                  const isEmpty = im.is_empty_frame === true
                  const leaving = flagging.has(im.id)
                  return (
                    <div
                      key={im.id}
                      style={{
                        position: 'relative',
                        flexShrink: 0,
                        opacity: leaving ? 0 : 1,
                        transform: leaving ? 'scale(0.92)' : 'scale(1)',
                        transition: 'opacity 180ms var(--ease-out), transform 180ms var(--ease-out)',
                      }}
                    >
                      <img
                        className="pressable"
                        role="button"
                        tabIndex={0}
                        aria-label={`Open photo from ${c.name}: ${im.species || 'Species not identified'}`}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                        src={imageUrl(im.file_url as string)}
                        alt={im.species || 'trail-camera photo'}
                        loading="lazy"
                        onClick={() => {
                          setImgReady(false)
                          setView(FIT)
                          setImgError(false)
                          setZoom({ list: imgs, idx: imgs.indexOf(im), cam: c.name })
                        }}
                        style={{
                          height: 74,
                          width: 100,
                          objectFit: 'cover',
                          borderRadius: 'var(--r-ctl)',
                          cursor: 'pointer',
                          background: 'var(--surface-2)',
                          opacity: isEmpty ? 0.4 : 1,
                          border: im.reviewed ? '2px solid var(--teal)' : 'none',
                        }}
                      />
                      {hidden && (
                        <button
                          onClick={() => flag(c.id, im.id, !isEmpty)}
                          disabled={leaving}
                          aria-label={isEmpty ? 'Mark photo as containing an animal' : 'Mark photo as empty'}
                          title={isEmpty ? 'Mark as animal (keep)' : 'Mark as empty (hide)'}
                          style={{
                            position: 'absolute',
                            top: 3,
                            right: 3,
                            width: 26,
                            height: 26,
                            borderRadius: 'var(--r-ctl)',
                            border: 'none',
                            cursor: 'pointer',
                            fontSize: 15,
                            lineHeight: '26px',
                            padding: 0,
                            fontWeight: 700,
                            background: isEmpty ? 'var(--go)' : 'rgba(0,0,0,0.6)',
                            color: isEmpty ? '#06210C' : '#fff',
                          }}
                        >
                          {isEmpty ? '+' : '×'}
                        </button>
                      )}
                      {hidden && isEmpty && im.animal_conf != null && (
                        <div
                          style={{
                            position: 'absolute',
                            bottom: 3,
                            left: 3,
                            fontSize: 9,
                            background: 'rgba(0,0,0,0.6)',
                            color: '#fff',
                            padding: '1px 4px',
                            borderRadius: 'var(--r-chip)',
                          }}
                        >
                          {Math.round(im.animal_conf * 100)}%
                        </div>
                      )}
                      {!isEmpty && im.species && (
                        <div
                          style={{
                            position: 'absolute',
                            bottom: 3,
                            left: 3,
                            fontSize: 9,
                            background: 'rgba(0,0,0,0.62)',
                            color: '#fff',
                            padding: '1px 5px',
                            borderRadius: 'var(--r-chip)',
                            maxWidth: 116,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {classLabel(im)}
                        </div>
                      )}
                    </div>
                  )
                })}
                {imgs.length === 0 && <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>{images[c.id] == null ? 'Loading photos…' : hidden ? 'No downloaded photos available.' : 'No photos in this view. Review photos marked empty, or sync for new photos.'}</div>}
              </div>
            </div>
          )
        })}
      </div>

      {zoom && (() => {
        const im = zoom.list[zoom.idx]
        const when = new Date(im.captured_at).toLocaleString(undefined, {
          weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
        })
        const what = im.is_empty_frame ? 'No animal detected' : classLabel(im) || 'Species not identified'
        return (
          <Overlay
            label={`${zoom.cam} · Photo ${zoom.idx + 1} of ${zoom.list.length}`}
            backLabel="Back to cameras"
            onClose={() => setZoom(null)}
            backdrop="rgba(0, 0, 0, 0.92)"
            style={{ flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 12 }}
            tools={
              // The two things you do with a photo once it is big: get closer, and keep it.
              <>
                <button
                  className="ov-tool"
                  onClick={toggleZoom}
                  aria-label={view.s > 1 ? 'Fit photo to screen' : 'Zoom in'}
                  title={view.s > 1 ? 'Fit to screen' : 'Zoom in — or double-tap, pinch, or scroll on the photo'}
                >
                  {view.s > 1 ? <MagnifyingGlassMinusIcon size={20} /> : <MagnifyingGlassPlusIcon size={20} />}
                </button>
                <button
                  className="ov-tool"
                  onClick={() => download(im)}
                  disabled={saving}
                  aria-label="Download photo"
                  title="Download photo"
                >
                  <DownloadSimpleIcon size={20} />
                </button>
              </>
            }
          >
            {(_close) => (
              <>
                {/* A stage of fixed size. Photos come off the cameras at mixed
                    aspect ratios, and letting each one set the frame meant the
                    picture jumped around the screen as you paged through. */}
                <div
                  ref={stageRef}
                  className="ov-panel lb-stage"
                  onClick={(e) => e.stopPropagation()}
                  onPointerDown={pointerDown}
                  onPointerMove={pointerMove}
                  onPointerUp={pointerUp}
                  onPointerCancel={pointerCancel}
                  style={{ cursor: view.s > 1 ? 'grab' : 'default' }}
                >
                  {imgError && <div role="alert" className="lb-status">Could not load this photo. Try another photo or return to cameras.</div>}
                  {!imgReady && !imgError && <span role="status" className="lb-status">Loading photo…</span>}
                  <img
                    ref={imgRef}
                    key={im.id}
                    src={imageUrl(im.file_url as string)}
                    alt={what}
                    draggable={false}
                    onLoad={() => setImgReady(true)}
                    onError={() => setImgError(true)}
                    style={{
                      maxWidth: '100%',
                      maxHeight: '100%',
                      borderRadius: 'var(--r-ctl)',
                      opacity: imgReady ? 1 : 0,
                      transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`,
                      transition:
                        view.snap && !reduced
                          ? 'opacity var(--d-fast) var(--ease-out), transform var(--d-base) var(--ease-out)'
                          : 'opacity var(--d-fast) var(--ease-out)',
                      willChange: 'transform',
                      display: imgError ? 'none' : undefined,
                    }}
                  />
                </div>
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    marginTop: 10, display: 'flex', alignItems: 'center', gap: 12,
                    background: 'rgba(0,0,0,0.55)', borderRadius: 'var(--r-ctl)', padding: '8px 14px',
                    fontSize: 13, color: '#fff', maxWidth: '94vw', flexWrap: 'wrap', justifyContent: 'center',
                  }}
                >
                  <b>{zoom.cam}</b>
                  <span>{what}</span>
                  <span style={{ opacity: 0.75 }}>{when}</span>
                  <span style={{ opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
                    {zoom.idx + 1} / {zoom.list.length}
                  </span>
                </div>
                <button
                  className="lb-nav"
                  style={{ left: 8 }}
                  disabled={zoom.idx === 0}
                  onClick={(e) => { e.stopPropagation(); step(-1) }}
                  aria-label="Previous photo"
                >
                  ‹
                </button>
                <button
                  className="lb-nav"
                  style={{ right: 8 }}
                  disabled={zoom.idx === zoom.list.length - 1}
                  onClick={(e) => { e.stopPropagation(); step(1) }}
                  aria-label="Next photo"
                >
                  ›
                </button>
              </>
            )}
          </Overlay>
        )
      })()}
    </div>
  )
}
