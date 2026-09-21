import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, imageUrl } from '../api'
import PhotoLightbox from '../components/PhotoLightbox'
import { useRefetchOnReturn } from '../hooks'
import './photos.css'

/**
 * Every animal photo from every camera, newest first. Pick the animals and
 * cameras you want with the chips, or none for everything. Empty frames and
 * hidden animals (Settings) never appear here.
 */

type Filters = {
  species: { id: string; common_name: string; count: number }[]
  cameras: { id: string; name: string; count: number }[]
}
type Photo = {
  image_id: string
  file_url: string
  captured_at: string
  camera: string
  camera_id: string
  label: string
  species_id: string | null
  group_size: number | null
}
type Page = { items: Photo[]; next_before: string | null }

const PICK_KEY = 'gs.photos.pick'
const PAGE = 60

function readPick(): { species: string[]; cameras: string[] } {
  try {
    const v = JSON.parse(localStorage.getItem(PICK_KEY) || '')
    return { species: v.species ?? [], cameras: v.cameras ?? [] }
  } catch {
    return { species: [], cameras: [] }
  }
}

const dayOf = (iso: string) => {
  const d = new Date(iso)
  const today = new Date()
  const y = new Date(today)
  y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
}
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

export default function Photos() {
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState<Filters | null>(null)
  const [pick, setPick] = useState(() => {
    // A link from a notification names the animal and camera; otherwise last choice.
    const sp = params.get('species')
    const cam = params.get('camera')
    if (sp || cam) return { species: sp ? sp.split(',') : [], cameras: cam ? cam.split(',') : [] }
    return readPick()
  })
  const [photos, setPhotos] = useState<Photo[] | null>(null)
  const [nextBefore, setNextBefore] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [err, setErr] = useState('')
  const [zoom, setZoom] = useState<number | null>(null)
  const wantImage = useRef<string | null>(params.get('image'))
  const request = useRef(0)
  const sentinel = useRef<HTMLDivElement>(null)

  const query = useCallback((before?: string | null) => {
    const q = new URLSearchParams()
    if (pick.species.length) q.set('species', pick.species.join(','))
    if (pick.cameras.length) q.set('cameras', pick.cameras.join(','))
    if (before) q.set('before', before)
    q.set('limit', String(PAGE))
    return `/photos?${q.toString()}`
  }, [pick])

  const load = useCallback(() => {
    const id = ++request.current
    setErr('')
    api<Page>(query())
      .then((page) => {
        if (id !== request.current) return
        setPhotos(page.items)
        setNextBefore(page.next_before)
      })
      .catch((e) => { if (id === request.current) setErr(e.message) })
    api<Filters>('/photos/filters').then(setFilters).catch(() => {})
  }, [query])

  useEffect(load, [load])
  useRefetchOnReturn(load, 120_000)

  // Open the photo a notification pointed at, once it is in the list.
  useEffect(() => {
    const want = wantImage.current
    if (!want || !photos) return
    wantImage.current = null
    setParams({}, { replace: true })
    const at = photos.findIndex((p) => p.image_id === want)
    if (at >= 0) setZoom(at)
  }, [photos, setParams])

  const loadMore = useCallback(() => {
    if (!nextBefore || loadingMore) return
    const id = request.current
    setLoadingMore(true)
    api<Page>(query(nextBefore))
      .then((page) => {
        if (id !== request.current) return
        setPhotos((prev) => [...(prev ?? []), ...page.items])
        setNextBefore(page.next_before)
      })
      .catch((e) => { if (id === request.current) setErr(e.message) })
      .finally(() => { if (id === request.current) setLoadingMore(false) })
  }, [nextBefore, loadingMore, query])

  // Keep filling as the person scrolls; the button below is for when that is not wanted.
  useEffect(() => {
    const el = sentinel.current
    if (!el || !nextBefore || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) loadMore() }, { rootMargin: '600px' })
    io.observe(el)
    return () => io.disconnect()
  }, [nextBefore, loadMore])

  function choose(next: { species: string[]; cameras: string[] }) {
    setPick(next)
    try { localStorage.setItem(PICK_KEY, JSON.stringify(next)) } catch { /* private mode */ }
  }
  const toggleIn = (list: string[], id: string) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  const everything = pick.species.length === 0 && pick.cameras.length === 0

  const grouped = useMemo(() => {
    const out: { day: string; start: number; items: Photo[] }[] = []
    ;(photos ?? []).forEach((p, i) => {
      const day = dayOf(p.captured_at)
      const last = out[out.length - 1]
      if (last && last.day === day) last.items.push(p)
      else out.push({ day, start: i, items: [p] })
    })
    return out
  }, [photos])

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <h1 className="page-title">Photos</h1>

      <div className="photos-filters">
        <div className="photos-filter-row">
          <button className="photos-chip" aria-pressed={everything} onClick={() => choose({ species: [], cameras: [] })}>
            Everything
          </button>
          {filters?.species.map((s) => (
            <button key={s.id} className="photos-chip" aria-pressed={pick.species.includes(s.id)}
              title={`${s.count} photos`}
              onClick={() => choose({ ...pick, species: toggleIn(pick.species, s.id) })}>
              {s.common_name}
            </button>
          ))}
        </div>
        {filters && filters.cameras.length > 1 && (
          <div className="photos-filter-row">
            <span className="photos-filter-name">Cameras</span>
            {filters.cameras.map((c) => (
              <button key={c.id} className="photos-chip" aria-pressed={pick.cameras.includes(c.id)}
                title={`${c.count} photos`}
                onClick={() => choose({ ...pick, cameras: toggleIn(pick.cameras, c.id) })}>
                {c.name}
              </button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="status-panel" role="alert">Could not load photos: {err}<button className="text-action" onClick={load}>Retry</button></div>}
      {!photos && !err && <div role="status" style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading photos…</div>}
      {photos && photos.length === 0 && (
        <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>
          {everything ? 'No animal photos yet.' : 'Nothing for that choice yet. Try fewer chips.'}
        </div>
      )}

      <div className="photos-grid">
        {grouped.map((g) => (
          <div key={g.day + g.start} style={{ display: 'contents' }}>
            <div className="photos-day">{g.day}</div>
            {g.items.map((p, j) => (
              <div
                key={p.image_id}
                className="photos-tile pressable"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                onClick={() => setZoom(g.start + j)}
              >
                <img src={imageUrl(p.file_url)} loading="lazy" alt={`${p.label} at ${p.camera}`} />
                <div className="photos-tile-meta">
                  <span className="photos-tile-label">{p.label}{p.group_size && p.group_size > 1 ? ` ×${p.group_size}` : ''}</span>
                  <span className="photos-tile-when">{timeOf(p.captured_at)}</span>
                </div>
                <div className="photos-tile-cam">{p.camera}</div>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div ref={sentinel} aria-hidden style={{ height: 1 }} />
      {nextBefore && (
        <button className="text-action photos-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : 'Show older photos'}
        </button>
      )}

      <p style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 18 }}>
        <Link to="/animals" style={{ color: 'inherit' }}>Animals by species and named animals</Link>
      </p>

      {zoom != null && photos && (
        <PhotoLightbox
          photos={photos.map((p) => ({ id: p.image_id, file_url: p.file_url, captured_at: p.captured_at, camera: p.camera, label: p.label }))}
          start={zoom}
          backLabel="Back to photos"
          onClose={() => setZoom(null)}
        />
      )}
    </div>
  )
}
