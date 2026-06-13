import { useEffect, useState } from 'react'
import { api } from '../api'

type Camera = {
  id: string
  name: string
  battery_pct: number | null
  signal_pct: number | null
  model: string | null
  image_count: number
  empty_count: number
  last_capture: string | null
}
type Img = {
  id: string
  captured_at: string
  file_url: string | null
  is_empty_frame: boolean | null
  reviewed: boolean
  animal_conf: number | null
}

function batteryColor(p: number | null): string {
  if (p == null) return 'var(--text-dim)'
  if (p < 25) return 'var(--skip)'
  if (p < 50) return 'var(--marginal)'
  return 'var(--go)'
}
function timeAgo(ts: string | null): string {
  if (!ts) return 'never'
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function Cameras() {
  const [cameras, setCameras] = useState<Camera[]>([])
  const [images, setImages] = useState<Record<string, Img[]>>({})
  const [showHidden, setShowHidden] = useState<Record<string, boolean>>({})
  const [syncing, setSyncing] = useState(false)
  const [zoom, setZoom] = useState<string | null>(null)

  async function loadImages(camId: string, includeEmpty: boolean) {
    const imgs = await api<Img[]>(`/cameras/${camId}/images?limit=80&include_empty=${includeEmpty}`)
    setImages((prev) => ({ ...prev, [camId]: imgs }))
  }

  async function loadCameras() {
    const cams = await api<Camera[]>('/cameras')
    setCameras(cams)
    await Promise.all(cams.map((c) => loadImages(c.id, !!showHidden[c.id])))
  }

  useEffect(() => {
    loadCameras().catch(() => {})
  }, [])

  function toggleHidden(camId: string) {
    const next = !showHidden[camId]
    setShowHidden((p) => ({ ...p, [camId]: next }))
    loadImages(camId, next).catch(() => {})
  }

  async function flag(camId: string, imgId: string, isEmpty: boolean) {
    try {
      await api(`/images/${imgId}/flag`, {
        method: 'POST',
        body: JSON.stringify({ is_empty: isEmpty }),
      })
      await loadImages(camId, !!showHidden[camId])
    } catch {
      /* ignore */
    }
  }

  async function syncNow() {
    setSyncing(true)
    try {
      await api('/cameras/sync', { method: 'POST' })
    } catch {
      /* ignore */
    }
    setTimeout(() => {
      loadCameras()
        .catch(() => {})
        .finally(() => setSyncing(false))
    }, 4000)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: 18, fontWeight: 700 }}>Cameras</div>
        <button
          className="btn"
          style={{ width: 'auto', marginLeft: 'auto', padding: '8px 14px' }}
          onClick={syncNow}
          disabled={syncing}
        >
          {syncing ? 'Syncing…' : 'Sync now'}
        </button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {cameras.map((c) => {
          const hidden = !!showHidden[c.id]
          const imgs = (images[c.id] || []).filter((im) => im.file_url)
          return (
            <div key={c.id} className="card" style={{ padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{c.model}</div>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, alignItems: 'center' }}>
                  <span style={{ color: batteryColor(c.battery_pct) }}>battery {c.battery_pct ?? '–'}%</span>
                  <span style={{ color: 'var(--text-dim)' }}>signal {c.signal_pct ?? '–'}%</span>
                  <span style={{ color: 'var(--text-dim)' }}>
                    {c.image_count - c.empty_count} animals · {timeAgo(c.last_capture)}
                  </span>
                </div>
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
                }}
              >
                {imgs.map((im) => {
                  const isEmpty = im.is_empty_frame === true
                  return (
                    <div key={im.id} style={{ position: 'relative', flexShrink: 0 }}>
                      <img
                        src={im.file_url as string}
                        onClick={() => setZoom(im.file_url)}
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
                            width: 20,
                            height: 20,
                            borderRadius: 5,
                            border: 'none',
                            cursor: 'pointer',
                            fontSize: 13,
                            lineHeight: '20px',
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
                    </div>
                  )
                })}
                {imgs.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>No photos</div>}
              </div>
            </div>
          )
        })}
      </div>

      {zoom && (
        <div
          onClick={() => setZoom(null)}
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.9)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 50,
            cursor: 'pointer',
          }}
        >
          <img src={zoom} style={{ maxWidth: '92vw', maxHeight: '92vh', borderRadius: 10 }} />
        </div>
      )}
    </div>
  )
}
