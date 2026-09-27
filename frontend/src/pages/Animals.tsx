import { CheckIcon } from '@phosphor-icons/react/dist/csr/Check'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { type Failure, api, getFresh, peek, peekMe, thumbUrl, whoAmI } from '../api'
import Overlay from '../components/Overlay'
import type { PhotoFix } from '../components/PhotoFix'
import PhotoLightbox, { morePhotosFailed } from '../components/PhotoLightbox'
import { NoteMark } from '../components/WorthALook'
import { useRefetchOnReturn } from '../hooks'
import { nightBefore, nightOf, whenSeen } from '../night'
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
  species_id?: string | null
  group_size: number | null
  notes_count: number
  fixed_by?: string | null
}
/** A page of a species' photos; the next starts after the last photo (time and id). */
type SpPage = { items: SpImg[]; next_before: string | null; next_before_id: string | null }
type Cursor = { before: string; before_id: string | null }
const GALLERY_PAGE = 60
type RepeatStatus = {
  state: 'never' | 'queued' | 'waiting' | 'running' | 'done' | 'failed'
  result: { new_candidates?: number; still_to_embed?: number } | null
  error: string | null
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

/** "Seen last night", "Seen Tuesday night", "Last seen 3 Sep": nights as Photos files
 *  them, not 24-hour spans (audit C-14). */
function lastSeen(s: string | null): string {
  if (!s) return 'Not seen yet'
  const thisWeek = nightOf(s) > nightBefore(nightOf(Date.now()), 7)
  return `${thisWeek ? 'Seen' : 'Last seen'} ${whenSeen(s)}`
}

/** "Wild boar #3": the name "Look for repeats" gives; anything else a hunter chose. */
const autoName = (label: string) => /^.+ #\d+$/.test(label.trim())

/** A refusal or a lost signal, in plain words, and what didn't happen. */
function failedWords(e: unknown, what: string): string {
  const x = e as Failure
  if (x.offline) return `No signal, so ${what}. Try again when you have a connection.`
  if (x.timeout) return `No answer from the server, so ${what}. Try again.`
  return `${what[0].toUpperCase()}${what.slice(1)}. ${x.message}`
}

// Counting every sighting is slower than a page on the estate box, but never forever.
const SLOW_MS = 30_000

export default function Animals() {
  // Leaving the page drops what it was still asking for, so the next tab on a thin
  // link isn't queued behind it; what this session last saw paints at once (K-08).
  const ctl = useRef<AbortController | null>(null)
  const signal = () => {
    if (!ctl.current || ctl.current.signal.aborted) ctl.current = new AbortController()
    return ctl.current.signal
  }
  useEffect(() => () => ctl.current?.abort(), [])

  // ── species browser ─────────────────────────────────────
  const [species, setSpecies] = useState<SpeciesRow[]>(() => peek<SpeciesRow[]>('/species/spotted')?.data ?? [])
  const [spErr, setSpErr] = useState('')
  const [spLoading, setSpLoading] = useState(true)
  const [galleryErr, setGalleryErr] = useState('')
  const galleryRequest = useRef(0)
  const [gallery, setGallery] = useState<{ sp: SpeciesRow; label: string | null } | null>(null)
  const [galleryImgs, setGalleryImgs] = useState<SpImg[] | null>(null)
  // Where the next page of the gallery starts; null when it is all here.
  const [galleryNext, setGalleryNext] = useState<Cursor | null>(null)
  const [galleryMore, setGalleryMore] = useState(false)
  // Why the last older page didn't come: under "Show older photos", and in the viewer.
  const [galleryMoreErr, setGalleryMoreErr] = useState('')
  const galleryInFlight = useRef<number | null>(null)
  const galleryEnd = useRef<HTMLDivElement>(null)
  const galleryBody = useRef<HTMLDivElement>(null)
  // Index into galleryImgs of the photo open in the viewer.
  const [zoom, setZoom] = useState<number | null>(null)
  // Photos a fix in the viewer took out of this gallery: they go when it closes.
  const leaving = useRef(new Set<string>())
  const [me, setMe] = useState<{ role: string } | null>(() => peekMe())
  useEffect(() => { whoAmI().then(setMe).catch(() => {}) }, [])
  const admin = me?.role === 'admin'

  // A sighting notification lands here as /animals?species=…&image=…: open that
  // species' gallery on that photo, then drop the query so closing the viewer or
  // pressing back behaves as if the person had browsed there themselves.
  const [params, setParams] = useSearchParams()
  const deepLink = useRef<{ species: string; image: string | null } | null>(
    params.get('species') ? { species: params.get('species')!, image: params.get('image') } : null,
  )

  function loadSpecies() {
    const sig = signal()
    setSpErr('')
    setSpLoading(true)
    getFresh<SpeciesRow[]>('/species/spotted', { signal: sig, timeoutMs: SLOW_MS }).then(({ data: rows }) => {
      setSpecies(rows)
      const want = deepLink.current
      if (!want) return
      const sp = rows.find((r) => r.id === want.species)
      if (sp) openGallery(sp, null)
      else { deepLink.current = null; setParams({}, { replace: true }) }
    }).catch((e) => { if (!sig.aborted) setSpErr(e.message) }).finally(() => setSpLoading(false))
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

  const galleryPath = (sp: SpeciesRow, label: string | null, after: Cursor | null) => {
    const q = new URLSearchParams({ limit: String(GALLERY_PAGE) })
    if (label) q.set('label', label)
    if (after) {
      q.set('before', after.before)
      if (after.before_id) q.set('before_id', after.before_id)
    }
    return `/species/${sp.id}/photos?${q.toString()}`
  }
  const cursorOf = (p: SpPage): Cursor | null => (p.next_before ? { before: p.next_before, before_id: p.next_before_id } : null)

  async function openGallery(sp: SpeciesRow, label: string | null) {
    const request = ++galleryRequest.current
    galleryInFlight.current = null
    setGalleryMore(false)
    setGalleryMoreErr('')
    setGalleryErr('')
    setGallery({ sp, label })
    setGalleryImgs(null)
    setGalleryNext(null)
    try {
      const page = await api<SpPage>(galleryPath(sp, label, null), { signal: signal(), timeoutMs: SLOW_MS })
      if (request !== galleryRequest.current) return
      setGalleryImgs(page.items)
      setGalleryNext(cursorOf(page))
    } catch {
      if (request === galleryRequest.current) setGalleryErr('Photos did not load. Check your signal and try again.')
    }
  }

  /** The next page of the gallery: it used to stop at 300 while the chip said 684. */
  function moreGallery() {
    const request = galleryRequest.current
    if (!gallery || !galleryNext || galleryInFlight.current === request) return
    galleryInFlight.current = request
    setGalleryMore(true)
    setGalleryMoreErr('')
    api<SpPage>(galleryPath(gallery.sp, gallery.label, galleryNext), { signal: signal(), timeoutMs: SLOW_MS })
      .then((page) => {
        if (request !== galleryRequest.current) return
        setGalleryImgs((prev) => {
          const have = new Set((prev ?? []).map((p) => p.image_id))
          return [...(prev ?? []), ...page.items.filter((p) => !have.has(p.image_id))]
        })
        setGalleryNext(cursorOf(page))
      })
      .catch((e) => { if (request === galleryRequest.current && (e as Error).name !== 'AbortError') setGalleryMoreErr(morePhotosFailed(e)) })
      .finally(() => {
        if (galleryInFlight.current !== request) return
        galleryInFlight.current = null
        setGalleryMore(false)
      })
  }
  const moreRef = useRef(moreGallery)
  moreRef.current = moreGallery
  // Keep filling as the gallery scrolls; the button is there for when that is not wanted.
  useEffect(() => {
    const el = galleryEnd.current
    if (!el || !galleryNext || !('IntersectionObserver' in window)) return
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) moreRef.current() },
      { root: galleryBody.current, rootMargin: '400px' })
    io.observe(el)
    return () => io.disconnect()
  }, [galleryNext, galleryImgs])

  function closeGallery() {
    galleryRequest.current++
    galleryInFlight.current = null
    setGallery(null)
    setGalleryImgs(null)
    setGalleryNext(null)
  }

  /** "Wrong?" in the viewer: the tile takes the new name now; a photo that isn't this
   *  animal any more (or has nothing in it) leaves when the viewer closes. */
  function photoFixed(id: string, fix: PhotoFix) {
    setGalleryImgs((imgs) => imgs && imgs.map((im) => (im.image_id === id
      ? { ...im, label: fix.empty ? im.label : fix.label, species_id: fix.species_id, fixed_by: fix.fixed_by } : im)))
    const off = fix.empty || fix.hidden || (!!gallery && fix.species_id !== gallery.sp.id)
      || (!!gallery?.label && fix.label !== gallery.label)
    if (off) leaving.current.add(id)
    else leaving.current.delete(id)
  }
  function closeViewer() {
    setZoom(null)
    if (!leaving.current.size) return
    const gone = new Set(leaving.current)
    leaving.current.clear()
    setGalleryImgs((imgs) => imgs && imgs.filter((im) => !gone.has(im.image_id)))
    loadSpecies()
  }

  // ── named animals (experimental) ────────────────────────
  const [items, setItems] = useState<Animal[]>(() => peek<Animal[]>('/animals')?.data ?? [])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [showAll, setShowAll] = useState(false)
  const [busy, setBusy] = useState('')

  function load() {
    const sig = signal()
    setErr('')
    setLoading(true)
    getFresh<Animal[]>('/animals', { signal: sig, timeoutMs: SLOW_MS })
      .then((got) => setItems(got.data))
      .catch((e) => { if (!sig.aborted) setErr(e.message) })
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

  // Naming an animal (admins): an inline field on its card, not a browser prompt.
  // Naming it confirms it, so "Look for repeats" keeps it as it is (audit C-10).
  const [naming, setNaming] = useState<{ id: string; draft: string; saving: boolean; err: string } | null>(null)

  async function saveName() {
    if (!naming || naming.saving) return
    const name = naming.draft.replace(/\s+/g, ' ').trim()
    const a = items.find((x) => x.id === naming.id)
    if (!name) { setNaming({ ...naming, err: 'Type a name first.' }); return }
    if (!a || name === a.label) { setNaming(null); return }
    setNaming({ ...naming, saving: true, err: '' })
    try {
      const r = await api<{ label: string }>(`/animals/${a.id}`, { method: 'PATCH', body: JSON.stringify({ label: name }), timeoutMs: 20_000 })
      setItems((xs) => xs.map((x) => (x.id === a.id ? { ...x, label: r.label, confirmed: true } : x)))
      setNaming(null)
    } catch (e) {
      setNaming((n) => n && { ...n, saving: false, err: failedWords(e, 'the name wasn’t saved') })
    }
  }

  // Merging keeps a name a hunter gave (audit C-11): the named one is the one merged
  // into, and with two or more names on the chosen animals the app asks which to keep.
  const [askName, setAskName] = useState<string[] | null>(null)

  async function mergeSelected(keep?: string) {
    const chosen = items.filter((a) => sel.has(a.id))
    if (chosen.length < 2) return
    const named = [...new Set(chosen.filter((a) => !autoName(a.label)).map((a) => a.label))]
    if (keep === undefined && named.length > 1) { setAskName(named); return }
    setAskName(null)
    const pool = chosen.filter((a) => (keep ? a.label === keep : !autoName(a.label)))
    const target = (pool.length ? pool : chosen).reduce((a, b) => (b.sightings > a.sightings ? b : a))
    setBusy('Merging…')
    setErr('')
    try {
      await api('/animals/merge', {
        method: 'POST',
        body: JSON.stringify({
          target_id: target.id,
          source_ids: chosen.filter((a) => a.id !== target.id).map((a) => a.id),
          ...(keep ? { label: keep } : {}),
        }),
        timeoutMs: 20_000,
      })
      setSel(new Set())
      load()
    } catch (e) {
      setErr(failedWords(e, 'they weren’t merged'))
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
      setErr(failedWords(e, 'they weren’t confirmed'))
    } finally {
      setBusy('')
    }
  }

  // "Look for repeats" runs on the server as a job of its own (minutes, the first time):
  // start it, then follow it here, and say in words where it is. Leaving the page
  // stops only the following; the job carries on.
  const [repeatMsg, setRepeatMsg] = useState('')
  const following = useRef(false)
  useEffect(() => () => { following.current = false }, [])

  async function followRepeats() {
    following.current = true
    const began = Date.now()
    while (following.current && Date.now() - began < 20 * 60_000) {
      await new Promise((res) => setTimeout(res, Date.now() - began < 60_000 ? 3000 : 10_000))
      if (!following.current) return
      let s: RepeatStatus
      try {
        s = await api<RepeatStatus>('/animals/recompute/status', { timeoutMs: 15_000 })
      } catch {
        continue // no signal for a moment: keep following it
      }
      if (s.state === 'waiting') setRepeatMsg('Waiting for the photo check to finish, then looking…')
      else if (s.state === 'queued' || s.state === 'running') setRepeatMsg('Looking for repeat visitors… This takes a few minutes.')
      else {
        following.current = false
        setBusy('')
        if (s.state === 'done') {
          const n = s.result?.new_candidates ?? 0
          const more = s.result?.still_to_embed ? ' Some older photos are still to go: tap again later.' : ''
          setRepeatMsg(`Done. ${n} possible repeat visitor${n === 1 ? '' : 's'} to look at.${more}`)
          setSel(new Set())
          load()
        } else {
          // The technical detail (in brackets) is for the server's log, not this line.
          const why = (s.error ?? '').replace(/\s*\([^)]*\)/g, '')
          setRepeatMsg(`It stopped before finishing. ${why} Try again later.`.replace(/\s+/g, ' ').trim())
        }
        return
      }
    }
    if (following.current) {
      following.current = false
      setBusy('')
      setRepeatMsg('Still going on the server. Come back to this page later.')
    }
  }

  async function recompute() {
    setBusy('Looking…')
    setErr('')
    try {
      const r = await api<{ status: string; note?: string }>('/animals/recompute', { method: 'POST' })
      setRepeatMsg(r.note ?? 'Looking for repeat visitors…')
      void followRepeats()
    } catch (e) {
      setErr(failedWords(e, 'it didn’t start'))
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
                  src={thumbUrl(sp.thumb_image_id)}
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
            {admin
              ? 'Matching is rough. Pick the sightings you know are the same animal and tap Merge.'
              : 'Matching is rough. Only an admin can merge or confirm them.'}
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
            {admin && (
              <button onClick={recompute} disabled={!!busy} className="an-btn an-btn--right" title="Scan new photos for repeat visitors">
                {busy === 'Looking…' ? 'Looking…' : 'Look for repeats'}
              </button>
            )}
          </div>

          {repeatMsg && <div className="an-dim" role="status" data-repeats>{repeatMsg}</div>}
          {err && <div className="an-error" role="alert">{err}</div>}

          {admin && sel.size > 0 && (
            <div className="card an-selbar">
              <span>{sel.size} picked</span>
              <button onClick={() => mergeSelected()} disabled={sel.size < 2 || !!busy} className="an-btn" style={{ opacity: sel.size < 2 ? 0.4 : 1 }}>
                Merge
              </button>
              <button onClick={confirmSelected} disabled={!!busy} className="an-btn">Confirm</button>
              <button onClick={() => { setSel(new Set()); setAskName(null) }} className="an-btn an-btn--right">Clear</button>
              {askName && (
                <div className="an-askname" role="group" aria-label="Which name to keep?">
                  <span>They have different names. Keep which?</span>
                  {askName.map((n) => (
                    <button key={n} className="an-btn" disabled={!!busy} onClick={() => mergeSelected(n)}>{n}</button>
                  ))}
                </div>
              )}
            </div>
          )}

          {loading ? (
            <div className="an-dim">Loading…</div>
          ) : items.length === 0 ? (
            <div className="card an-empty">
              {admin ? <>Nothing yet. Tap <b className="an-strong">Look for repeats</b>. It takes a few minutes.</> : 'Nothing yet. An admin looks for repeat visitors.'}
            </div>
          ) : shown.length === 0 ? (
            <div className="an-dim">
              {admin ? 'No repeat visitors found. Tap Show all to browse single sightings and merge the ones you recognise.' : 'No repeat visitors found. Tap Show all to browse single sightings.'}
            </div>
          ) : (
            <div className="an-grid">
              {shown.map((a) => {
                const on = sel.has(a.id)
                return (
                  <div
                    key={a.id}
                    onClick={admin ? () => toggle(a.id) : undefined}
                    className={`card an-animal${admin ? ' pressable' : ''}`}
                    style={{ outline: on ? '2px solid var(--teal)' : '2px solid transparent' }}
                  >
                    <div className="an-animal-photo">
                      {a.thumb_image_id && (
                        <img
                          src={thumbUrl(a.thumb_image_id)}
                          loading="lazy"
                          alt={a.label}
                        />
                      )}
                      {admin && <div className="an-animal-check" style={{ background: on ? 'var(--teal)' : 'rgba(0,0,0,.5)' }}>
                        {on ? <CheckIcon size={13} weight="bold" /> : null}
                      </div>}
                      {a.confirmed && <div className="an-animal-confirmed">confirmed</div>}
                      {a.sightings >= 2 && <div className="an-animal-count">{a.sightings} visits</div>}
                    </div>
                    <div className="an-animal-body">
                      {naming?.id === a.id ? (
                        <form className="an-name-form" onClick={(e) => e.stopPropagation()} aria-busy={naming.saving}
                          onSubmit={(e) => { e.preventDefault(); void saveName() }}
                          onKeyDown={(e) => { if (e.key === 'Escape' && !naming.saving) { e.stopPropagation(); setNaming(null) } }}>
                          <label className="sr-only" htmlFor={`name-${a.id}`}>Name this animal</label>
                          <input id={`name-${a.id}`} className="input" value={naming.draft} maxLength={60} autoFocus
                            disabled={naming.saving} aria-invalid={!!naming.err}
                            onChange={(e) => setNaming({ ...naming, draft: e.target.value, err: '' })} />
                          <div className="an-name-buttons">
                            <button type="submit" className="an-btn" disabled={naming.saving}>{naming.saving ? 'Saving…' : 'Save'}</button>
                            <button type="button" className="an-btn" disabled={naming.saving} onClick={() => setNaming(null)}>Cancel</button>
                          </div>
                          {naming.err && <p className="an-error" role="alert">{naming.err}</p>}
                        </form>
                      ) : admin ? (
                        <button type="button" className="an-animal-name an-animal-name--edit"
                          onClick={(e) => { e.stopPropagation(); setNaming({ id: a.id, draft: a.label, saving: false, err: '' }) }}
                          aria-label={`Name ${a.label}`} title="Tap to name">
                          {a.label}
                        </button>
                      ) : (
                        <div className="an-animal-name">{a.label}</div>
                      )}
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
                {(() => {
                  // The whole count, as the chip says it, not only what has loaded.
                  const n = gallery.label ? gallery.sp.classes.find((c) => c.label === gallery.label)?.count : gallery.sp.count
                  return n != null ? `${n} photo${n === 1 ? '' : 's'}` : galleryImgs ? '' : 'loading…'
                })()}
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
            <div className="an-gallery-body" ref={galleryBody}>
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
                    <img src={thumbUrl(im.image_id)} loading="lazy" alt={im.label} />
                    <NoteMark count={im.notes_count} />
                    <div className="an-gallery-caption">
                      <span className="an-gallery-label">{im.label}</span>
                      <span className="an-gallery-date">
                        {new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
              <div ref={galleryEnd} aria-hidden style={{ height: 1 }} />
              {galleryMoreErr && galleryNext && !galleryMore && <div className="status-panel" role="alert">{galleryMoreErr}</div>}
              {galleryNext && (
                <button className="text-action an-gallery-more" onClick={moreGallery} disabled={galleryMore}>
                  {galleryMore ? 'Loading…' : 'Show older photos'}
                </button>
              )}
            </div>
          </div>
        )}</Overlay>
      )}

      {/* ── Fullscreen photo ──────────────────────────────── */}
      {zoom != null && galleryImgs && (
        <PhotoLightbox
          photos={galleryImgs.map((im) => ({
            id: im.image_id, file_url: im.file_url, captured_at: im.captured_at, camera: im.camera, label: im.label,
            notes_count: im.notes_count, species_id: im.species_id, fixed_by: im.fixed_by,
          }))}
          start={zoom}
          backLabel="Back to gallery"
          zIndex={60}
          onClose={closeViewer}
          onNotesChange={(id, n) => setGalleryImgs((imgs) => imgs && imgs.map((im) => (im.image_id === id ? { ...im, notes_count: n } : im)))}
          onFixed={photoFixed}
          hasMore={!!galleryNext}
          onNeedMore={moreGallery}
          moreError={galleryMoreErr}
        />
      )}
    </div>
  )
}
