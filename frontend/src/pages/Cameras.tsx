import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { api, imageUrl } from '../api'
import Overlay from '../components/Overlay'
import { useRefetchOnReturn } from '../hooks'

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

export default function Cameras() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [images, setImages] = useState<Record<string, Img[]>>({})
  const [showHidden, setShowHidden] = useState<Record<string, boolean>>({})
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<Zoom | null>(null)
  // Photos being marked empty/animal, held long enough to leave rather than
  // blink out when the strip reloads underneath them.
  const [flagging, setFlagging] = useState<Set<string>>(new Set())
  // The strip a moment before it changes shape. See toggleHidden.
  const [swapping, setSwapping] = useState<string | null>(null)
  const [imgReady, setImgReady] = useState(true)
  const swipe = useRef<{ x: number; t: number } | null>(null)

  async function loadImages(camId: string, includeEmpty: boolean) {
    const imgs = await api<Img[]>(`/cameras/${camId}/images?limit=80&include_empty=${includeEmpty}`)
    setImages((prev) => ({ ...prev, [camId]: imgs }))
  }

  async function loadCameras() {
    try {
      const cams = await api<Camera[]>('/cameras')
      setCameras(cams)
      setErr('')
      await Promise.all(cams.map((c) => loadImages(c.id, !!showHidden[c.id])))
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  useEffect(() => {
    loadCameras()
  }, [])
  useRefetchOnReturn(loadCameras)

  // Lightbox keyboard navigation: ← → to move. Escape belongs to Overlay now, so
  // that every panel in the app answers it rather than only this one.
  useEffect(() => {
    if (!zoom) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') step(-1)
      if (e.key === 'ArrowRight') step(1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
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
    setZoom({ ...zoom, idx: i })
  }

  /**
   * Swipe to turn the page — on a phone this is the whole navigation, and two
   * 46px arrows were standing in for it. A flick counts even when it barely
   * moves: past 0.11 px/ms the intent is unambiguous, which is the same
   * threshold a drag-to-dismiss uses.
   */
  function swipeEnd(e: ReactPointerEvent) {
    const s = swipe.current
    swipe.current = null
    if (!s) return
    const dx = e.clientX - s.x
    const dt = Math.max(1, e.timeStamp - s.t)
    if (Math.abs(dx) < 12) return   // that was a tap
    if (Math.abs(dx) > 60 || Math.abs(dx) / dt > 0.11) step(dx < 0 ? 1 : -1)
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
      loadImages(camId, next).catch(() => {})
      requestAnimationFrame(() => setSwapping(null))
    }, 110)
  }

  async function flag(camId: string, imgId: string, isEmpty: boolean) {
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
      /* ignore */
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
              setSyncMsg(n > 0 ? `Done — ${n} new photo${n === 1 ? '' : 's'}` : 'Done — no new photos')
              done = true
            } else if (s.status === 'error') {
              setSyncMsg('Sync failed — see Settings for details')
              done = true
            } else {
              setSyncMsg('Syncing…')
            }
          } catch {
            /* transient — keep polling */
          }
        }
        if (!done) setSyncMsg('Still running in the background — photos will appear as they arrive.')
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
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
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
          Couldn't load cameras: {err} — pull down or tap Sync now to retry.
        </div>
      )}

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
                      background: healthMeta(c.health.status).color, borderRadius: 5, padding: '2px 7px',
                    }}
                  >
                    {healthMeta(c.health.status).label}
                  </span>
                )}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ color: batteryColor(c.battery_pct) }}>battery {c.battery_pct ?? '–'}%</span>
                  <span style={{ color: 'var(--text-dim)' }}>signal {c.signal_pct ?? '–'}%</span>
                  {c.photo_limit != null && (
                    <span style={{ color: creditColor(c.photo_count, c.photo_limit) }}>
                      photos {c.photo_count ?? '?'}/{c.photo_limit}
                    </span>
                  )}
                  <span style={{ color: 'var(--text-dim)' }}>
                    {c.image_count - c.empty_count} animals · {timeAgo(c.last_capture)}
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
                    borderRadius: 8,
                    padding: '4px 10px',
                    cursor: 'pointer',
                    fontSize: 12,
                  }}
                >
                  {hidden ? 'Hide empty frames' : `Review ${c.empty_count} hidden`}
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
                        src={imageUrl(im.file_url as string)}
                        alt={im.species || 'trail-camera photo'}
                        loading="lazy"
                        onClick={() => {
                          setImgReady(false)
                          setZoom({ list: imgs, idx: imgs.indexOf(im), cam: c.name })
                        }}
                        style={{
                          height: 74,
                          width: 100,
                          objectFit: 'cover',
                          borderRadius: 8,
                          cursor: 'pointer',
                          background: 'var(--surface-2)',
                          opacity: isEmpty ? 0.4 : 1,
                          border: im.reviewed ? '2px solid var(--teal)' : 'none',
                        }}
                      />
                      {hidden && (
                        <button
                          onClick={() => flag(c.id, im.id, !isEmpty)}
                          title={isEmpty ? 'Mark as animal (keep)' : 'Mark as empty (hide)'}
                          style={{
                            position: 'absolute',
                            top: 3,
                            right: 3,
                            width: 26,
                            height: 26,
                            borderRadius: 6,
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
                            borderRadius: 4,
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
                            borderRadius: 4,
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
                {imgs.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>No photos</div>}
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
        const what = im.is_empty_frame ? 'No animal' : classLabel(im) || 'Unclassified'
        return (
          <Overlay
            onClose={() => setZoom(null)}
            backdrop="rgba(0, 0, 0, 0.92)"
            style={{ flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 12 }}
          >
            {(_close) => (
              <>
                {/* A stage of fixed size. Photos come off the cameras at mixed
                    aspect ratios, and letting each one set the frame meant the
                    picture jumped around the screen as you paged through. */}
                <div
                  className="ov-panel"
                  onClick={(e) => e.stopPropagation()}
                  onPointerDown={(e) => { swipe.current = { x: e.clientX, t: e.timeStamp } }}
                  onPointerUp={swipeEnd}
                  onPointerCancel={() => { swipe.current = null }}
                  style={{
                    width: '94vw',
                    height: '80vh',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    touchAction: 'pan-y',
                  }}
                >
                  <img
                    key={im.id}
                    src={imageUrl(im.file_url as string)}
                    alt={what}
                    draggable={false}
                    onLoad={() => setImgReady(true)}
                    style={{
                      maxWidth: '100%',
                      maxHeight: '100%',
                      borderRadius: 10,
                      opacity: imgReady ? 1 : 0,
                      transition: 'opacity var(--d-fast) var(--ease-out)',
                    }}
                  />
                </div>
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    marginTop: 10, display: 'flex', alignItems: 'center', gap: 12,
                    background: 'rgba(0,0,0,0.55)', borderRadius: 10, padding: '8px 14px',
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
