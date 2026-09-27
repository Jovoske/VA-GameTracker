import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { type Got, ageLabel, api, getFresh, noAnswerWords, peek, thumbUrl } from '../api'
import PhotoLightbox, { type LightboxPhoto, morePhotosFailed } from '../components/PhotoLightbox'
import HighlightStrip, { NoteMark } from '../components/WorthALook'
import type { PhotoFix } from '../components/PhotoFix'
import { useRefetchOnReturn } from '../hooks'
import { photoHeading } from '../night'
import './photos.css'

/**
 * Every animal photo from every camera, newest first, under headings by night as
 * the server counts nights ("Last night", "Thu night": 18:00 to 06:00 on the estate's
 * clock) and by day for the daytime ones ("Today", "Yesterday"). Pick the animals and
 * cameras you want with the chips, or none for everything. Empty frames and hidden animals (Settings) never appear here. Above
 * them, the photos the team marked "Worth a look", once there are any.
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
  notes_count: number
  fixed_by?: string | null
}
/** A page, and where the next starts: the last photo's time and id (a burst can
 *  share one time, and paging by time alone skipped its frames at a page break). */
type Page = { items: Photo[]; next_before: string | null; next_before_id?: string | null }
type Cursor = { before: string; before_id: string | null }
const cursorOf = (p: Page): Cursor | null => (p.next_before ? { before: p.next_before, before_id: p.next_before_id ?? null } : null)
type Failure = Error & { status?: number }

const toViewer = (p: Photo): LightboxPhoto => ({
  id: p.image_id, file_url: p.file_url, captured_at: p.captured_at, camera: p.camera, label: p.label, notes_count: p.notes_count,
  species_id: p.species_id, fixed_by: p.fixed_by,
})

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

const timeOf = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

/** Newest first, as the server orders the feed: by when the photo was taken, then id. */
const feedOrder = (a: Photo, b: Photo) =>
  Date.parse(b.captured_at) - Date.parse(a.captured_at) || (b.image_id < a.image_id ? -1 : b.image_id > a.image_id ? 1 : 0)

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
  // The newest page from earlier in this session paints at once, then the network
  // replaces it: coming back to Photos from another tab is not "Loading…" again.
  const [photos, setPhotos] = useState<Photo[] | null>(null)
  const [nextBefore, setNextBefore] = useState<Cursor | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  // Why the last older page didn't come: under "Show older photos", and in the viewer.
  const [moreErr, setMoreErr] = useState('')
  // A new choice of chips is on its way: the old photos dim under a "Loading…".
  const [pending, setPending] = useState(false)
  const [err, setErr] = useState('')
  // The feed on screen is what this session saw earlier, because the network didn't answer.
  const [savedCopy, setSavedCopy] = useState<Got<Page> | null>(null)
  const [zoom, setZoom] = useState<number | null>(null)
  // A photo a link named that isn't in the loaded pages: opened with the frames
  // taken just before it (its burst), or on its own.
  const [single, setSingle] = useState<{ items: Photo[]; start: number } | null>(null)
  const [notice, setNotice] = useState('')
  // Bumped when a note changes from the grid, so the strip above asks again.
  const [notesTick, setNotesTick] = useState(0)
  const wantImage = useRef<string | null>(params.get('image'))
  // When that photo was taken (an alert's link carries it), to find it however many
  // newer photos came in since (audit K-07).
  const wantAt = useRef<string | null>(params.get('at'))
  const request = useRef(0)
  // The older page being asked for, by the request it belongs to. A new choice of
  // chips drops it, so a slow page can neither hold "Loading…" for good nor land in
  // the new list (audit C-01).
  const inFlight = useRef<number | null>(null)
  // Photos a fix in the viewer took out of this list: they go when the viewer closes.
  const leaving = useRef(new Set<string>())
  const anyFix = useRef(false)
  const sentinel = useRef<HTMLDivElement>(null)
  const photosRef = useRef(photos)
  photosRef.current = photos
  const nextBeforeRef = useRef(nextBefore)
  nextBeforeRef.current = nextBefore
  // What the page is still asking for; leaving the page drops it (audit K-08).
  const ctl = useRef<AbortController | null>(null)
  const signal = () => {
    if (!ctl.current || ctl.current.signal.aborted) ctl.current = new AbortController()
    return ctl.current.signal
  }
  useEffect(() => () => ctl.current?.abort(), [])

  const query = useCallback((after?: Cursor | null) => {
    const q = new URLSearchParams()
    if (pick.species.length) q.set('species', pick.species.join(','))
    if (pick.cameras.length) q.set('cameras', pick.cameras.join(','))
    if (after) {
      q.set('before', after.before)
      if (after.before_id) q.set('before_id', after.before_id)
    }
    q.set('limit', String(PAGE))
    return `/photos?${q.toString()}`
  }, [pick])

  const load = useCallback(() => {
    const id = ++request.current
    inFlight.current = null
    setLoadingMore(false)
    setMoreErr('')
    setErr('')
    const hit = peek<Page>(query())
    if (hit) { setPhotos(hit.data.items); setNextBefore(cursorOf(hit.data)) } else setPending(true)
    getFresh<Page>(query(), { signal: signal() })
      .then((got) => {
        if (id !== request.current) return
        setPhotos(got.data.items)
        setNextBefore(cursorOf(got.data))
        setSavedCopy(got.stale ? got : null)
      })
      .catch((e) => { if (id === request.current && (e as Error).name !== 'AbortError') setErr(e.message) })
      .finally(() => { if (id === request.current) setPending(false) })
  }, [query])

  // The chips, once they arrive, also clean the saved pick: an animal hidden or
  // turned off since, or a camera taken down, filtered the feed invisibly with no
  // chip lit (audit C-27, I-07). Only against a fresh list, never a saved one.
  const loadFilters = useCallback(() => {
    const hit = peek<Filters>('/photos/filters')
    if (hit) setFilters(hit.data)
    getFresh<Filters>('/photos/filters', { signal: signal() })
      .then((got) => {
        setFilters(got.data)
        if (got.stale) return
        const sp = new Set(got.data.species.map((x) => x.id))
        const cams = new Set(got.data.cameras.map((x) => x.id))
        setPick((p) => {
          const next = { species: p.species.filter((x) => sp.has(x)), cameras: p.cameras.filter((x) => cams.has(x)) }
          if (next.species.length === p.species.length && next.cameras.length === p.cameras.length) return p
          try { localStorage.setItem(PICK_KEY, JSON.stringify(next)) } catch { /* private mode */ }
          return next
        })
      })
      .catch(() => {})
  }, [])

  // Not with a photo open: the list would change under it (and under a note being
  // written, which is often when someone steps out to copy a message). The strip
  // above asks again by itself.
  const viewing = useRef(false)
  viewing.current = zoom != null || single != null

  /**
   * Back in the app: put the photos that came in since into the list.
   *
   * This used to start the list over from the newest 60, which threw away every
   * page scrolled through and, with a photo open, pulled the list out from under
   * the viewer (a black screen, audit C-02 and I-01). Now the pages already loaded
   * stay, and only when more than a page of new photos came in (the hunter was away
   * a long time) does it start over from the newest.
   *
   * Merged by when each photo was taken, not only put on top: the cameras deliver
   * at different delays (SPYPOINT's sync, UBox, an FTP upload), so a photo that
   * arrives late can be older than the newest one already on screen. Anything down
   * to the oldest photo loaded belongs in the list; older ones come with "Show older".
   */
  const loadNewer = useCallback(() => {
    const top = photosRef.current?.[0]
    if (!top) { load(); return }
    const id = request.current
    loadFilters()
    getFresh<Page>(query(), { signal: signal() })
      .then((got) => {
        if (id !== request.current || viewing.current) return
        setSavedCopy(got.stale ? got : null)
        if (got.stale) return
        const page = got.data
        const since = Date.parse(top.captured_at)
        const oldest = page.items[page.items.length - 1]
        if (page.items.length >= PAGE && oldest && Date.parse(oldest.captured_at) > since) {
          // The list starts over: an older page still on its way belongs to the one
          // thrown away. Landing after the new newest page, it left a hole in the feed
          // down to where the old list had got to (audit C-01).
          request.current++
          inFlight.current = null
          setLoadingMore(false)
          setPending(false)
          setMoreErr('')
          setPhotos(page.items)
          setNextBefore(cursorOf(page))
          return
        }
        setPhotos((prev) => {
          if (!prev?.length) return page.items
          const have = new Set(prev.map((p) => p.image_id))
          const floor = Date.parse(prev[prev.length - 1].captured_at)
          const fresh = page.items.filter((p) => !have.has(p.image_id) && (!nextBeforeRef.current || Date.parse(p.captured_at) >= floor))
          return fresh.length ? [...prev, ...fresh].sort(feedOrder) : prev
        })
      })
      .catch(() => {})
  }, [load, loadFilters, query])

  useEffect(load, [load])
  useEffect(loadFilters, [loadFilters])
  useRefetchOnReturn(() => { if (!viewing.current) loadNewer() }, 120_000)

  // Open the photo a notification pointed at: in the list when it is on the first
  // page; otherwise, by the time the alert carries, with the frames just before it
  // (a push tapped the next morning can be many pages down by then); otherwise
  // asked for by itself. A photo gone since (hidden, or deleted) says so.
  useEffect(() => {
    const want = wantImage.current
    if (!want || !photos) return
    const taken = Date.parse(wantAt.current ?? '')
    wantImage.current = null
    wantAt.current = null
    setParams({}, { replace: true })
    const at = photos.findIndex((p) => p.image_id === want)
    if (at >= 0) { setZoom(at); return }
    const alone = () => api<Photo>(`/photos/${encodeURIComponent(want)}`, { timeoutMs: 20_000 })
      .then((p) => setSingle({ items: [p], start: 0 }))
    const burst = () => {
      const q = new URLSearchParams()
      if (pick.species.length) q.set('species', pick.species.join(','))
      q.set('before', new Date(taken + 1).toISOString())
      q.set('limit', '6')
      return api<Page>(`/photos?${q.toString()}`, { timeoutMs: 20_000 }).then((page) => {
        const i = page.items.findIndex((p) => p.image_id === want)
        if (i < 0) return alone()
        setSingle({ items: page.items, start: i })
      })
    }
    ;(Number.isFinite(taken) ? burst() : alone())
      .catch((e: Failure) => setNotice(e.status === 404 || e.status === 422
        ? 'That photo isn’t available any more.'
        : `Couldn’t open that photo. ${e.message}`))
  }, [photos, setParams, pick])

  /** A note was added or removed in a viewer: the tile's marker and the strip follow. */
  const notesChanged = useCallback((id: string, n: number) => {
    setPhotos((prev) => prev && prev.map((p) => (p.image_id === id ? { ...p, notes_count: n } : p)))
  }, [])

  const loadMore = useCallback(() => {
    if (!nextBefore || inFlight.current === request.current) return
    const id = request.current
    inFlight.current = id
    setLoadingMore(true)
    setMoreErr('')
    api<Page>(query(nextBefore), { signal: signal(), timeoutMs: 20_000 })
      .then((page) => {
        if (id !== request.current) return
        // Never twice: a late photo merged on return may sit on a page boundary.
        setPhotos((prev) => {
          const have = new Set((prev ?? []).map((p) => p.image_id))
          return [...(prev ?? []), ...page.items.filter((p) => !have.has(p.image_id))]
        })
        setNextBefore(cursorOf(page))
      })
      .catch((e) => { if (id === request.current && (e as Error).name !== 'AbortError') setMoreErr(morePhotosFailed(e)) })
      .finally(() => {
        if (inFlight.current !== id) return
        inFlight.current = null
        setLoadingMore(false)
      })
  }, [nextBefore, query])

  /** "Wrong?" in the viewer: the tile takes the new name now; a photo that no longer
   *  belongs here (nothing in it, a hidden animal, or not one of the chosen animals)
   *  goes when the viewer closes. */
  const photoFixed = useCallback((id: string, fix: PhotoFix) => {
    setPhotos((prev) => prev && prev.map((p) => (p.image_id === id
      ? { ...p, label: fix.empty ? p.label : fix.label, species_id: fix.species_id, fixed_by: fix.fixed_by }
      : p)))
    const off = fix.empty || fix.hidden || (pick.species.length > 0 && !pick.species.includes(fix.species_id ?? ''))
    if (off) leaving.current.add(id)
    else leaving.current.delete(id)
    anyFix.current = true
  }, [pick])
  const closeViewer = useCallback(() => {
    setZoom(null)
    setSingle(null)
    if (!anyFix.current) return
    anyFix.current = false
    const gone = new Set(leaving.current)
    leaving.current.clear()
    if (gone.size) setPhotos((prev) => prev && prev.filter((p) => !gone.has(p.image_id)))
    // The chips' counts and the team's strip above say what the photos are now.
    loadFilters()
    setNotesTick((t) => t + 1)
  }, [loadFilters])

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

  // By night, as the server counts them: last night's photos after midnight are
  // under "Last night" with the rest of it, not under "Today" (audit I-27); and the
  // daytime ones under the day, as whenSeen says them ("Today", "Yesterday").
  const grouped = useMemo(() => {
    const out: { day: string; label: string; start: number; items: Photo[] }[] = []
    const now = Date.now()
    ;(photos ?? []).forEach((p, i) => {
      const { key, label } = photoHeading(p.captured_at, now)
      const last = out[out.length - 1]
      if (last && last.day === key) last.items.push(p)
      else out.push({ day: key, label, start: i, items: [p] })
    })
    return out
  }, [photos])

  return (
    <div style={{ maxWidth: 760, margin: '0 auto' }}>
      <h1 className="page-title">Photos</h1>

      {notice && <div className="status-panel" role="status">{notice}<button className="text-action" onClick={() => setNotice('')}>OK</button></div>}
      <HighlightStrip refreshKey={notesTick} backLabel="Back to photos" onChange={notesChanged}
        onFixed={photoFixed} onClosed={closeViewer} />

      <div className="photos-filters" aria-busy={pending}>
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

      {pending && photos && <div role="status" className="photos-pending">Loading…</div>}
      {err && <div className="status-panel" role="alert">Could not load photos. {err}<button className="text-action" onClick={load}>Try again</button></div>}
      {savedCopy && !err && (
        <div className="status-panel" role="status">
          {noAnswerWords(savedCopy.why)} Showing what you saw {ageLabel(savedCopy.at)}.
          <button className="text-action" onClick={load}>Try again</button>
        </div>
      )}
      {!photos && !err && <div role="status" style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading photos…</div>}
      {photos && photos.length === 0 && (
        <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>
          {everything ? 'No animal photos yet.' : 'Nothing for that choice yet. Try fewer chips.'}
        </div>
      )}

      <div className="photos-grid" data-pending={pending || undefined}>
        {grouped.map((g) => (
          <div key={g.day + g.start} style={{ display: 'contents' }}>
            <div className="photos-day">{g.label}</div>
            {g.items.map((p, j) => (
              <div
                key={p.image_id}
                className="photos-tile pressable"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                onClick={() => setZoom(g.start + j)}
              >
                <img src={thumbUrl(p.image_id)} loading="lazy" alt={`${p.label} at ${p.camera}`} />
                <NoteMark count={p.notes_count} />
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
      {moreErr && nextBefore && !loadingMore && <div className="status-panel" role="alert">{moreErr}</div>}
      {nextBefore && (
        <button className="text-action photos-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : 'Show older photos'}
        </button>
      )}

      <p style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 18 }}>
        <Link to="/animals" style={{ color: 'inherit', display: 'inline-flex', alignItems: 'center', minHeight: 44 }}>Animals by species and named animals</Link>
      </p>

      {zoom != null && photos && (
        <PhotoLightbox
          photos={photos.map(toViewer)}
          start={zoom}
          backLabel="Back to photos"
          onClose={closeViewer}
          onNotesChange={(id, n) => { notesChanged(id, n); setNotesTick((t) => t + 1) }}
          onFixed={photoFixed}
          hasMore={!!nextBefore}
          onNeedMore={loadMore}
          moreError={moreErr}
        />
      )}
      {single && (
        <PhotoLightbox
          photos={single.items.map(toViewer)}
          start={single.start}
          backLabel="Back to photos"
          onClose={closeViewer}
          onNotesChange={(id, n) => { notesChanged(id, n); setNotesTick((t) => t + 1) }}
          onFixed={(id, fix) => {
            photoFixed(id, fix)
            setSingle((cur) => cur && { ...cur, items: cur.items.map((p) => (p.image_id === id ? { ...p, label: fix.label } : p)) })
          }}
        />
      )}
    </div>
  )
}
