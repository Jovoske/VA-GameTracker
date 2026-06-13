import { useEffect, useState } from 'react'
import { api } from '../api'

type Camera = {
  id: string
  name: string
  battery_pct: number | null
  signal_pct: number | null
  model: string | null
  image_count: number
  last_capture: string | null
}

type Img = { id: string; captured_at: string; file_url: string | null }

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
  const [syncing, setSyncing] = useState(false)
  const [zoom, setZoom] = useState<string | null>(null)

  async function load() {
    const cams = await api<Camera[]>('/cameras')
    setCameras(cams)
    const map: Record<string, Img[]> = {}
    await Promise.all(
      cams.map(async (c) => {
        map[c.id] = await api<Img[]>(`/cameras/${c.id}/images?limit=8`)
      }),
    )
    setImages(map)
  }

  useEffect(() => {
    load().catch(() => {})
  }, [])

  async function syncNow() {
    setSyncing(true)
    try {
      await api('/cameras/sync', { method: 'POST' })
    } catch {
      /* ignore */
    }
    setTimeout(() => {
      load()
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

      {cameras.length === 0 && (
        <div style={{ color: 'var(--text-dim)', fontSize: 14 }}>
          No cameras yet — press “Sync now” to pull from SPYPOINT.
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {cameras.map((c) => {
          const imgs = (images[c.id] || []).filter((im) => im.file_url)
          return (
            <div key={c.id} className="card" style={{ padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <div style={{ fontWeight: 600, fontSize: 15 }}>{c.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{c.model}</div>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 14, fontSize: 12, alignItems: 'center' }}>
                  <span style={{ color: batteryColor(c.battery_pct) }}>
                    battery {c.battery_pct ?? '–'}%
                  </span>
                  <span style={{ color: 'var(--text-dim)' }}>signal {c.signal_pct ?? '–'}%</span>
                  <span style={{ color: 'var(--text-dim)' }}>
                    {c.image_count} photos · {timeAgo(c.last_capture)}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 10, overflowX: 'auto' }}>
                {imgs.map((im) => (
                  <img
                    key={im.id}
                    src={im.file_url as string}
                    onClick={() => setZoom(im.file_url)}
                    style={{
                      height: 74,
                      width: 100,
                      objectFit: 'cover',
                      borderRadius: 8,
                      cursor: 'pointer',
                      background: 'var(--surface-2)',
                      flexShrink: 0,
                    }}
                  />
                ))}
                {imgs.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>No stored photos yet</div>
                )}
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
