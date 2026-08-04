import { useEffect, useMemo, useState } from 'react'
import { api, imageUrl } from '../api'
import { useRefetchOnReturn } from '../hooks'

type SpeciesRow = {
  id: string
  name: string
  count: number
  last_seen: string | null
  thumb_image_id: string | null
  classes: { label: string; count: number }[]
}
type SpImg = {
  image_id: string
  file_url: string
  captured_at: string
  camera: string
  label: string
  group_size: number | null
}
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
  // ── species browser ─────────────────────────────────────
  const [species, setSpecies] = useState<SpeciesRow[]>([])
  const [spErr, setSpErr] = useState('')
  const [gallery, setGallery] = useState<{ sp: SpeciesRow; label: string | null } | null>(null)
  const [galleryImgs, setGalleryImgs] = useState<SpImg[] | null>(null)
  const [zoom, setZoom] = useState<SpImg | null>(null)

  function loadSpecies() {
    api<SpeciesRow[]>('/species/spotted').then(setSpecies).catch((e) => setSpErr(e.message))
  }
  useEffect(loadSpecies, [])
  useRefetchOnReturn(loadSpecies, 120_000)

  async function openGallery(sp: SpeciesRow, label: string | null) {
    setGallery({ sp, label })
    setGalleryImgs(null)
    try {
      const q = label ? `?label=${encodeURIComponent(label)}` : ''
      setGalleryImgs(await api<SpImg[]>(`/species/${sp.id}/images${q}`))
    } catch {
      setGalleryImgs([])
    }
  }
  function closeGallery() {
    setGallery(null)
    setGalleryImgs(null)
  }

  // ── individual re-ID (experimental) ─────────────────────
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

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 12 }}>Animals</div>

      {/* ── Spotted on the estate ─────────────────────────── */}
      <div className="card" style={{ padding: 18, marginBottom: 18 }}>
        <div style={{ ...labelStyle, marginBottom: 12 }}>SPOTTED ON THE ESTATE</div>
        {spErr && <div style={{ fontSize: 13, color: 'var(--skip)' }}>Couldn't load: {spErr}</div>}
        {!spErr && species.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>No sightings yet.</div>
        )}
        {species.map((sp, i) => (
          <div
            key={sp.id}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              padding: '10px 0',
              borderTop: i > 0 ? '1px solid var(--border)' : 'none',
            }}
          >
            <div
              onClick={() => openGallery(sp, null)}
              style={{
                width: 56, height: 56, borderRadius: 10, overflow: 'hidden',
                background: 'var(--surface-2)', flexShrink: 0, cursor: 'pointer',
              }}
              title={`All ${sp.name} photos`}
            >
              {sp.thumb_image_id && (
                <img
                  src={imageUrl(`/api/images/${sp.thumb_image_id}/file`)}
                  loading="lazy"
                  alt={sp.name}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                />
              )}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                onClick={() => openGallery(sp, null)}
                style={{ display: 'flex', alignItems: 'baseline', gap: 8, cursor: 'pointer' }}
                title={`All ${sp.name} photos`}
              >
                <span style={{ fontSize: 15, fontWeight: 600 }}>{sp.name}</span>
                <span style={{ fontSize: 12, color: 'var(--text-dim)', fontVariantNumeric: 'tabular-nums' }}>
                  ×{sp.count}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0 }}>
                  last {fmt(sp.last_seen)}
                </span>
              </div>
              {sp.classes.length > 1 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                  {sp.classes.map((cl) => (
                    <button
                      key={cl.label}
                      onClick={() => openGallery(sp, cl.label)}
                      title={`View the ${cl.count} ${cl.label} photos`}
                      style={{
                        fontSize: 12, background: 'var(--surface-2)', border: '1px solid var(--border)',
                        color: 'var(--text)', borderRadius: 7, padding: '3px 9px', cursor: 'pointer',
                      }}
                    >
                      {cl.label} <span style={{ color: 'var(--text-dim)' }}>×{cl.count}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span
              onClick={() => openGallery(sp, null)}
              style={{ color: 'var(--text-dim)', fontSize: 17, cursor: 'pointer', paddingLeft: 2 }}
            >
              ›
            </span>
          </div>
        ))}
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
          Every species the cameras have seen — tap one for its photos, or a class (Stag, Sow + piglets…)
          for just those.
        </div>
      </div>

      {/* ── Individual recognition (experimental) ─────────── */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Individual recognition</div>
        <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--marginal)', border: '1px solid var(--border)', borderRadius: 6, padding: '1px 6px' }}>
          experimental
        </span>
        <button onClick={recompute} disabled={!!busy} style={btn} title="Re-embed new sightings and regenerate candidates">
          {busy === 'Recomputing…' ? 'Recomputing…' : 'Recompute'}
        </button>
      </div>

      {err && <div style={{ color: 'var(--skip)', fontSize: 13, marginBottom: 10 }}>{err}</div>}

      <div className="card" style={{ padding: 16, marginBottom: 14, lineHeight: 1.5, fontSize: 13 }}>
        <div style={{ ...labelStyle, marginBottom: 8 }}>HOW THIS WORKS — HONESTLY</div>
        Telling apart individual animals of the same species from night-time infrared photos is
        beyond the current model. It can only group <b>near-duplicate frames</b> — the same animal
        within one visit — so most sightings stand alone. Treat this as a manual tool: when <i>you</i>{' '}
        recognise the same animal across sightings, select them and <b>Merge</b> into one named
        individual. Nothing here is an asserted identity.
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, fontSize: 12, color: 'var(--text-dim)' }}>
        <span><b style={{ color: 'var(--text)' }}>{grouped.length}</b> grouped</span>
        <span><b style={{ color: 'var(--text)' }}>{items.length - grouped.length}</b> single</span>
        <span>biggest group <b style={{ color: 'var(--text)' }}>{biggest}</b></span>
        {items.length > 0 && (
          <button onClick={() => setShowAll((v) => !v)} style={{ ...btn, marginLeft: 'auto' }}>
            {showAll ? `Showing all ${items.length}` : `Show all ${items.length}`}
          </button>
        )}
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
      ) : items.length === 0 ? (
        <div className="card" style={{ padding: 16, color: 'var(--text-dim)', fontSize: 13, lineHeight: 1.5 }}>
          Nothing here yet. Tap <b style={{ color: 'var(--text)' }}>Recompute</b> (top right) to scan your
          sightings for repeat visitors — it takes a few minutes and runs on the server.
        </div>
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
                      src={imageUrl(`/api/images/${a.thumb_image_id}/file`)}
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

      {/* ── Species photo gallery ─────────────────────────── */}
      {gallery && (
        <div
          onClick={closeGallery}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)', zIndex: 50, display: 'flex', padding: 16 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="card"
            style={{ padding: 0, maxWidth: 760, width: '100%', margin: 'auto', overflow: 'hidden', display: 'flex', flexDirection: 'column', maxHeight: '90vh' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 700, fontSize: 15 }}>{gallery.sp.name}</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {galleryImgs ? `${galleryImgs.length} photo${galleryImgs.length === 1 ? '' : 's'}` : 'loading…'}
              </span>
              <button
                onClick={closeGallery}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text-dim)', borderRadius: 8, padding: '4px 10px', cursor: 'pointer', fontSize: 13 }}
              >
                Close
              </button>
              {gallery.sp.classes.length > 1 && (
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', width: '100%' }}>
                  <button
                    onClick={() => openGallery(gallery.sp, null)}
                    style={{
                      fontSize: 12, borderRadius: 7, padding: '3px 9px', cursor: 'pointer',
                      border: '1px solid var(--border)',
                      background: gallery.label === null ? 'var(--go)' : 'var(--surface-2)',
                      color: gallery.label === null ? '#06210C' : 'var(--text)',
                      fontWeight: gallery.label === null ? 700 : 400,
                    }}
                  >
                    All ×{gallery.sp.count}
                  </button>
                  {gallery.sp.classes.map((cl) => (
                    <button
                      key={cl.label}
                      onClick={() => openGallery(gallery.sp, cl.label)}
                      style={{
                        fontSize: 12, borderRadius: 7, padding: '3px 9px', cursor: 'pointer',
                        border: '1px solid var(--border)',
                        background: gallery.label === cl.label ? 'var(--go)' : 'var(--surface-2)',
                        color: gallery.label === cl.label ? '#06210C' : 'var(--text)',
                        fontWeight: gallery.label === cl.label ? 700 : 400,
                      }}
                    >
                      {cl.label} ×{cl.count}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div style={{ overflowY: 'auto', padding: 12 }}>
              {!galleryImgs && <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading…</div>}
              {galleryImgs && galleryImgs.length === 0 && (
                <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>No photos.</div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
                {galleryImgs?.map((im) => (
                  <div
                    key={im.image_id}
                    onClick={() => setZoom(im)}
                    style={{ background: 'var(--surface-2)', borderRadius: 8, overflow: 'hidden', cursor: 'pointer' }}
                  >
                    <img src={imageUrl(im.file_url)} loading="lazy" alt={im.label} style={{ width: '100%', height: 104, objectFit: 'cover', display: 'block' }} />
                    <div style={{ padding: '4px 7px', fontSize: 11, color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{im.label}</span>
                      <span style={{ flexShrink: 0 }}>
                        {new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Fullscreen photo ──────────────────────────────── */}
      {zoom && (
        <div
          onClick={() => setZoom(null)}
          style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.92)', zIndex: 60, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 12 }}
        >
          <img src={imageUrl(zoom.file_url)} alt={zoom.label} style={{ maxWidth: '94vw', maxHeight: '82vh', borderRadius: 10 }} />
          <div style={{ marginTop: 10, background: 'rgba(0,0,0,0.55)', borderRadius: 10, padding: '8px 14px', fontSize: 13, color: '#fff', display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
            <b>{zoom.camera}</b>
            <span>{zoom.label}</span>
            <span style={{ opacity: 0.75 }}>
              {new Date(zoom.captured_at).toLocaleString(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
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
