import { CheckIcon } from '@phosphor-icons/react/dist/csr/Check'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, imageUrl } from '../api'
import Overlay from '../components/Overlay'
import PhotoLightbox from '../components/PhotoLightbox'
import { useRefetchOnReturn } from '../hooks'
import './animals.css'

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
  s ? new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'never'

/** "today", "yesterday", "Tuesday" or "3 Sep": when this animal was last on camera. */
function lastSeen(s: string | null): string {
  if (!s) return 'Not seen yet'
  const d = new Date(s)
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (days < 1) return 'Seen today'
  if (days === 1) return 'Seen yesterday'
  if (days < 7) return `Seen ${d.toLocaleDateString(undefined, { weekday: 'long' })}`
  return `Last seen ${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}`
}

export default function Animals() {
  // ── species browser ─────────────────────────────────────
  const [species, setSpecies] = useState<SpeciesRow[]>([])
  const [spErr, setSpErr] = useState('')
  const [spLoading, setSpLoading] = useState(true)
  const [galleryErr, setGalleryErr] = useState('')
  const galleryRequest = useRef(0)
  const [gallery, setGallery] = useState<{ sp: SpeciesRow; label: string | null } | null>(null)
  const [galleryImgs, setGalleryImgs] = useState<SpImg[] | null>(null)
  // Index into galleryImgs of the photo open in the viewer.
  const [zoom, setZoom] = useState<number | null>(null)

  // A sighting notification lands here as /animals?species=…&image=…: open that
  // species' gallery on that photo, then drop the query so closing the viewer or
  // pressing back behaves as if the person had browsed there themselves.
  const [params, setParams] = useSearchParams()
  const deepLink = useRef<{ species: string; image: string | null } | null>(
    params.get('species') ? { species: params.get('species')!, image: params.get('image') } : null,
  )

  function loadSpecies() {
    setSpErr('')
    setSpLoading(true)
    api<SpeciesRow[]>('/species/spotted').then((rows) => {
      setSpecies(rows)
      const want = deepLink.current
      if (!want) return
      const sp = rows.find((r) => r.id === want.species)
      if (sp) openGallery(sp, null)
      else { deepLink.current = null; setParams({}, { replace: true }) }
    }).catch((e) => setSpErr(e.message)).finally(() => setSpLoading(false))
  }
  useEffect(loadSpecies, [])
  useEffect(() => {
    const want = deepLink.current
    if (!want || !galleryImgs) return
    deepLink.current = null
    setParams({}, { replace: true })
    if (galleryImgs.length === 0) return
    const at = want.image ? galleryImgs.findIndex((im) => im.image_id === want.image) : -1
    setZoom(at >= 0 ? at : 0)
  }, [galleryImgs, setParams])
  useRefetchOnReturn(loadSpecies, 120_000)

  async function openGallery(sp: SpeciesRow, label: string | null) {
    const request = ++galleryRequest.current
    setGalleryErr('')
    setGallery({ sp, label })
    setGalleryImgs(null)
    try {
      const q = label ? `?label=${encodeURIComponent(label)}` : ''
      const photos = await api<SpImg[]>(`/species/${sp.id}/images${q}`)
      if (request === galleryRequest.current) setGalleryImgs(photos)
    } catch {
      if (request === galleryRequest.current) setGalleryErr('Photos did not load. Check your signal and try again.')
    }
  }
  function closeGallery() {
    galleryRequest.current++
    setGallery(null)
    setGalleryImgs(null)
  }

  // ── named animals (experimental) ────────────────────────
  const [items, setItems] = useState<Animal[]>([])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState('')

  function load() {
    setErr('')
    setLoading(true)
    api<Animal[]>('/animals')
      .then((d) => setItems(d))
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const grouped = useMemo(() => items.filter((a) => a.sightings >= 2), [items])
  const shown = showAll ? items : grouped

  function toggle(id: string) {
    setSel((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function rename(a: Animal) {
    const name = window.prompt('Name this animal', a.label)
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
    setBusy('Looking…')
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
    <div className="an-page">
      <h1 className="page-title">Animals</h1>

      {/* ── On your cameras ──────────────────────────────── */}
      <div className="card an-species-card">
        <h2 className="sect">On your cameras</h2>
        {spErr && <div role="alert" className="an-error">Animals did not load. {spErr}<button className="text-action" onClick={loadSpecies}>Try again</button></div>}
        {spLoading && <div role="status" className="an-dim">Loading…</div>}
        {!spLoading && !spErr && species.length === 0 && (
          <div className="an-dim">No animals on camera yet.</div>
        )}
        {species.map((sp) => (
          <div key={sp.id} className="an-species-row">
            <div
              className="pressable an-species-thumb"
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
              onClick={() => openGallery(sp, null)}
              title={`All ${sp.name} photos`}
            >
              {sp.thumb_image_id && (
                <img
                  src={imageUrl(`/api/images/${sp.thumb_image_id}/file`)}
                  loading="lazy"
                  alt={sp.name}
                />
              )}
            </div>
            <div className="an-species-body">
              <div
                className="an-species-head"
                onClick={() => openGallery(sp, null)}
                title={`All ${sp.name} photos`}
              >
                <span className="an-species-name">{sp.name}</span>
                <span className="an-species-meta">
                  {lastSeen(sp.last_seen)} · {sp.count} photo{sp.count === 1 ? '' : 's'}
                </span>
              </div>
              {sp.classes.length > 1 && (
                <div className="an-chips">
                  {sp.classes.map((cl) => (
                    <button
                      key={cl.label}
                      className="an-chip"
                      onClick={() => openGallery(sp, cl.label)}
                      title={`${cl.label} photos`}
                    >
                      {cl.label} <span className="an-dim">{cl.count}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span
              className="an-species-arrow"
              onClick={() => openGallery(sp, null)}
              aria-hidden="true"
            >
              ›
            </span>
          </div>
        ))}
      </div>

      {/* ── Named animals (experimental) ─────────────────── */}
      <details className="an-fold">
        <summary>Named animals <span className="an-dim">(experimental)</span></summary>

        <div className="an-fold-body">
          <p className="an-fold-note">
            Matching is rough. Pick the sightings you know are the same animal and tap Merge.
          </p>

          <div className="an-toolbar">
            <span className="an-dim">
              <b className="an-strong">{grouped.length}</b> repeat visitor{grouped.length === 1 ? '' : 's'}
            </span>
            {items.length > 0 && (
              <button onClick={() => setShowAll((v) => !v)} className="an-btn" aria-pressed={showAll}>
                {showAll ? 'Repeat visitors only' : `Show all ${items.length}`}
              </button>
            )}
            <button onClick={recompute} disabled={!!busy} className="an-btn an-btn--right" title="Scan new photos for repeat visitors">
              {busy === 'Looking…' ? 'Looking…' : 'Look for repeats'}
            </button>
          </div>

          {err && <div className="an-error" role="alert">{err}</div>}

          {sel.size > 0 && (
            <div className="card an-selbar">
              <span>{sel.size} picked</span>
              <button onClick={mergeSelected} disabled={sel.size < 2 || !!busy} className="an-btn" style={{ opacity: sel.size < 2 ? 0.4 : 1 }}>
                Merge
              </button>
              <button onClick={confirmSelected} disabled={!!busy} className="an-btn">Confirm</button>
              <button onClick={() => setSel(new Set())} className="an-btn an-btn--right">Clear</button>
            </div>
          )}

          {loading ? (
            <div className="an-dim">Loading…</div>
          ) : items.length === 0 ? (
            <div className="card an-empty">
              Nothing yet. Tap <b className="an-strong">Look for repeats</b>. It takes a few minutes.
            </div>
          ) : shown.length === 0 ? (
            <div className="an-dim">
              No repeat visitors found. Tap Show all to browse single sightings and merge the ones you recognise.
            </div>
          ) : (
            <div className="an-grid">
              {shown.map((a) => {
                const on = sel.has(a.id)
                return (
                  <div
                    key={a.id}
                    onClick={() => toggle(a.id)}
                    className="card pressable an-animal"
                    style={{ outline: on ? '2px solid var(--teal)' : '2px solid transparent' }}
                  >
                    <div className="an-animal-photo">
                      {a.thumb_image_id && (
                        <img
                          src={imageUrl(`/api/images/${a.thumb_image_id}/file`)}
                          loading="lazy"
                          alt={a.label}
                        />
                      )}
                      <div className="an-animal-check" style={{ background: on ? 'var(--teal)' : 'rgba(0,0,0,.5)' }}>
                        {on ? <CheckIcon size={13} weight="bold" /> : null}
                      </div>
                      {a.confirmed && <div className="an-animal-confirmed">confirmed</div>}
                      {a.sightings >= 2 && <div className="an-animal-count">{a.sightings} visits</div>}
                    </div>
                    <div className="an-animal-body">
                      <div
                        className="an-animal-name"
                        onClick={(e) => { e.stopPropagation(); rename(a) }}
                        title="Tap to name"
                      >
                        {a.label}
                      </div>
                      <div className="an-animal-meta">
                        {fmt(a.first_seen)}{a.last_seen !== a.first_seen ? ` to ${fmt(a.last_seen)}` : ''} · {a.cameras} camera{a.cameras === 1 ? '' : 's'}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </details>

      {/* ── Species photo gallery ─────────────────────────── */}
      {gallery && (
        <Overlay onClose={closeGallery} label={`${gallery.sp.name} photos`} backLabel="Back to animals">{(close) => (
          <div
            onClick={(e) => e.stopPropagation()}
            className="card ov-panel an-gallery"
          >
            <div className="an-gallery-head">
              <span className="an-gallery-title">{gallery.sp.name}</span>
              <span className="an-dim">
                {galleryImgs ? `${galleryImgs.length} photo${galleryImgs.length === 1 ? '' : 's'}` : 'loading…'}
              </span>
              <button onClick={close} className="an-btn an-btn--right">
                Close
              </button>
              {gallery.sp.classes.length > 1 && (
                <div className="an-chips an-chips--full">
                  <button
                    onClick={() => openGallery(gallery.sp, null)}
                    className={`an-chip${gallery.label === null ? ' an-chip--on' : ''}`}
                  >
                    All {gallery.sp.count}
                  </button>
                  {gallery.sp.classes.map((cl) => (
                    <button
                      key={cl.label}
                      onClick={() => openGallery(gallery.sp, cl.label)}
                      className={`an-chip${gallery.label === cl.label ? ' an-chip--on' : ''}`}
                    >
                      {cl.label} {cl.count}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="an-gallery-body">
              {galleryErr && <div className="status-panel" role="alert">{galleryErr}<button className="text-action" onClick={() => openGallery(gallery.sp, gallery.label)}>Try again</button></div>}
              {!galleryImgs && !galleryErr && <div role="status" className="an-dim an-gallery-status">Loading photos…</div>}
              {galleryImgs && galleryImgs.length === 0 && (
                <div className="an-dim an-gallery-status">No photos.</div>
              )}
              <div className="an-gallery-grid">
                {galleryImgs?.map((im, i) => (
                  <div
                    key={im.image_id}
                    className="pressable an-gallery-item"
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                    onClick={() => setZoom(i)}
                  >
                    <img src={imageUrl(im.file_url)} loading="lazy" alt={im.label} />
                    <div className="an-gallery-caption">
                      <span className="an-gallery-label">{im.label}</span>
                      <span className="an-gallery-date">
                        {new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}</Overlay>
      )}

      {/* ── Fullscreen photo ──────────────────────────────── */}
      {zoom != null && galleryImgs && (
        <PhotoLightbox
          photos={galleryImgs.map((im) => ({ id: im.image_id, file_url: im.file_url, captured_at: im.captured_at, camera: im.camera, label: im.label }))}
          start={zoom}
          backLabel="Back to gallery"
          zIndex={60}
          onClose={() => setZoom(null)}
        />
      )}
    </div>
  )
}
