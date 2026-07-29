import { useEffect, useMemo, useState } from 'react'
import { api, authedImageUrl } from '../api'

type Animal = {
  id: string
  label: string
  species: string | null
  species_id: string | null
  status: string
  sightings: number
  first_seen: string | null
  last_seen: string | null
  cameras: number
  confirmed: boolean
  thumb_image_id: string | null
}

const fmt = (s: string | null) =>
  s ? new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '—'
const labelStyle = { fontSize: 12, color: 'var(--text-dim)', letterSpacing: '.05em' } as const

export default function Animals() {
  const [items, setItems] = useState<Animal[]>([])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState('')

  function load() {
    setLoading(true)
    api<Animal[]>('/animals')
      .then((d) => setItems(d))
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const grouped = useMemo(() => items.filter((a) => a.sightings >= 2), [items])
  const shown = showAll ? items : grouped
  const biggest = items.reduce((m, a) => Math.max(m, a.sightings), 0)

  function toggle(id: string) {
    setSel((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function rename(a: Animal) {
    const name = window.prompt('Name this individual', a.label)
    if (!name || name === a.label) return
    await api(`/animals/${a.id}`, { method: 'PATCH', body: JSON.stringify({ label: name }) })
    setItems((xs) => xs.map((x) => (x.id === a.id ? { ...x, label: name } : x)))
  }

  async function mergeSelected() {
    const chosen = items.filter((a) => sel.has(a.id))
    if (chosen.length < 2) return
    const target = chosen.reduce((a, b) => (b.sightings > a.sightings ? b : a))
    setBusy('Merging…')
    try {
      await api('/animals/merge', {
        method: 'POST',
        body: JSON.stringify({
          target_id: target.id,
          source_ids: chosen.filter((a) => a.id !== target.id).map((a) => a.id),
        }),
      })
      setSel(new Set())
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function confirmSelected() {
    setBusy('Confirming…')
    try {
      for (const id of sel) await api(`/animals/${id}/confirm`, { method: 'POST' })
      setSel(new Set())
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  async function recompute() {
    setBusy('Recomputing…')
    try {
      await api('/animals/recompute', { method: 'POST' })
      setSel(new Set())
      load()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  if (err) return <div style={{ color: 'var(--text-dim)' }}>Couldn't load: {err}</div>

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 18 }}>Animals</div>
        <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--marginal)', border: '1px solid var(--border)', borderRadius: 6, padding: '1px 6px' }}>
          experimental
        </span>
        <button onClick={recompute} disabled={!!busy} style={btn} title="Re-embed new sightings and regenerate candidates">
          {busy === 'Recomputing…' ? 'Recomputing…' : 'Recompute'}
        </button>
      </div>

      <div className="card" style={{ padding: 16, marginBottom: 14, lineHeight: 1.5, fontSize: 13 }}>
        <div style={{ ...labelStyle, marginBottom: 8 }}>HOW THIS WORKS — HONESTLY</div>
        Telling apart individual animals of the same species from night-time infrared photos is
        beyond the current model. On this estate's {items.reduce((n, a) => n + a.sightings, 0)} sightings it
        could only group <b>near-duplicate frames</b> — the same animal within one visit — so most
        sightings stand alone. Treat this as a manual tool: when <i>you</i> recognise the same animal
        across sightings, select them and <b>Merge</b> into one named individual. Nothing here is an
        asserted identity.
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, fontSize: 12, color: 'var(--text-dim)' }}>
        <span><b style={{ color: 'var(--text)' }}>{grouped.length}</b> grouped</span>
        <span><b style={{ color: 'var(--text)' }}>{items.length - grouped.length}</b> single</span>
        <span>biggest group <b style={{ color: 'var(--text)' }}>{biggest}</b></span>
        <button onClick={() => setShowAll((v) => !v)} style={{ ...btn, marginLeft: 'auto' }}>
          {showAll ? `Showing all ${items.length}` : `Show all ${items.length}`}
        </button>
      </div>

      {sel.size > 0 && (
        <div className="card" style={{ padding: '10px 14px', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 10, position: 'sticky', top: 8, zIndex: 5 }}>
          <span style={{ fontSize: 13 }}>{sel.size} selected</span>
          <button onClick={mergeSelected} disabled={sel.size < 2 || !!busy} style={{ ...btn, opacity: sel.size < 2 ? 0.4 : 1 }}>
            Merge into one
          </button>
          <button onClick={confirmSelected} disabled={!!busy} style={btn}>Confirm</button>
          <button onClick={() => setSel(new Set())} style={{ ...btn, marginLeft: 'auto' }}>Clear</button>
        </div>
      )}

      {loading ? (
        <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
      ) : shown.length === 0 ? (
        <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>
          No grouped candidates yet — toggle “Show all” to browse individual sightings and merge them.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
          {shown.map((a) => {
            const on = sel.has(a.id)
            return (
              <div
                key={a.id}
                onClick={() => toggle(a.id)}
                className="card"
                style={{ padding: 0, overflow: 'hidden', cursor: 'pointer', outline: on ? '2px solid var(--teal)' : 'none' }}
              >
                <div style={{ position: 'relative', height: 110, background: 'var(--surface-2)' }}>
                  {a.thumb_image_id && (
                    <img
                      src={authedImageUrl(`/api/images/${a.thumb_image_id}/file`)}
                      loading="lazy"
                      alt={a.label}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                    />
                  )}
                  <div style={{ position: 'absolute', top: 6, left: 6, width: 18, height: 18, borderRadius: 4, background: on ? 'var(--teal)' : 'rgba(0,0,0,.5)', border: '1px solid rgba(255,255,255,.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, color: '#fff' }}>
                    {on ? '✓' : ''}
                  </div>
                  {a.confirmed && (
                    <div style={{ position: 'absolute', top: 6, right: 6, fontSize: 10, background: 'var(--go)', color: '#000', borderRadius: 4, padding: '1px 5px', fontWeight: 700 }}>
                      confirmed
                    </div>
                  )}
                  {a.sightings >= 2 && (
                    <div style={{ position: 'absolute', bottom: 6, right: 6, fontSize: 10, background: 'rgba(0,0,0,.6)', color: '#fff', borderRadius: 4, padding: '1px 5px' }}>
                      ×{a.sightings}
                    </div>
                  )}
                </div>
                <div style={{ padding: 8 }}>
                  <div
                    onClick={(e) => { e.stopPropagation(); rename(a) }}
                    title="Click to rename"
                    style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                  >
                    {a.label}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                    {fmt(a.first_seen)}{a.last_seen !== a.first_seen ? `–${fmt(a.last_seen)}` : ''} · {a.cameras} cam{a.cameras === 1 ? '' : 's'}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const btn = {
  marginLeft: 8,
  background: 'var(--surface-2)',
  border: '1px solid var(--border)',
  color: 'var(--text)',
  borderRadius: 8,
  padding: '5px 10px',
  fontSize: 12,
  cursor: 'pointer',
} as const
