import { DownloadSimpleIcon } from '@phosphor-icons/react/dist/csr/DownloadSimple'
import { MagnifyingGlassMinusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassMinus'
import { MagnifyingGlassPlusIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlassPlus'
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { type Failure, api, imageUrl, plainWords, whoAmI } from '../api'
import { useReducedMotion } from '../hooks'
import { estateStamp } from '../night'
import Overlay from './Overlay'
import { FixSheet, type PhotoFix, type Saved, fixSpecies, markEmpty, undoFix } from './PhotoFix'
import PhotoNotesPanel from './PhotoNotes'

/**
 * The one photo viewer. Cameras, the species gallery on Animals and the class
 * gallery on Insights all open photos through this, so paging, zoom, download
 * and the back button behave the same everywhere. There used to be three: one
 * with paging and two that were a bare <img> you could only look at.
 *
 * Under the photo are the team's notes on it and, for members and admins, the
 * "Worth a look" button (PhotoNotes). That band has a fixed height, so the photo
 * keeps its place as you page between photos with and without notes. On a phone
 * turned on its side (and a wide screen) the band goes beside the photo instead,
 * where it costs width the photo has to spare rather than height it hasn't.
 *
 * A photo with a person or a vehicle in it (Photos' "People & vehicles", admins only)
 * has neither notes nor "Wrong?": it never goes to the team. It has "Nobody in it?"
 * instead, for a feeder or a rock the detector read as a vehicle, with Undo.
 *
 * Members and admins also have "Wrong?" (PhotoFix): say what the animal really is,
 * or that there's nothing in it. The viewer shows the new name at once, with Undo,
 * on the photo and on the other photos of its visit that followed it; the list that
 * opened it hears of each through `onFixed`.
 *
 * A list that has more photos than it has loaded (Photos, the species gallery, a
 * camera's strip) says so with `hasMore`, and the viewer asks for the next page
 * (`onNeedMore`) as you swipe towards the end, rather than stopping at "Photo 60 of
 * 60" (audit C-13). When that page can't come, the list says why (`moreError`) and
 * the viewer says so at the end, with Try again, rather than waiting on it.
 */

/** Why the next page of photos didn't come, in words, for `moreError`. */
export function morePhotosFailed(e: unknown): string {
  const x = e as Failure
  if (x.offline) return 'No signal, so older photos didn’t load.'
  if (x.timeout) return 'No answer from the server, so older photos didn’t load.'
  return `Older photos didn’t load. ${plainWords(x.message || '')}`.trim()
}

export type LightboxPhoto = {
  id: string
  file_url: string
  captured_at: string
  camera: string
  /** What is in the frame: "Stag", "Sow + piglets (4)", "No animal". */
  label: string
  /** The team's notes on it, when the list knows; 0 spares a call per photo. */
  notes_count?: number
  /** Marked "nothing in it" (Cameras shows these on request). A note on it keeps it. */
  empty?: boolean
  /** The species it shows, when the list knows, to mark it on "Wrong?". */
  species_id?: string | null
  /** Who said what it is, when a hunter did ("Fixed by Pedro"). */
  fixed_by?: string | null
  /** A frame of people or vehicles (Photos' admin-only "People & vehicles"). */
  people?: { person: boolean; vehicle: boolean } | null
}

/** A fix made in this viewer, and how to take it back. */
type Change = { id: string; fix: Saved; before: PhotoFix; choice: string }

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

/** `PL19_2026-09-04_22-05-07.jpg`: the camera and the moment on the estate's clock,
 * as the server names the same photo (routes_images.download_name). */
function downloadName(cam: string, capturedAt: string): string {
  const stem = cam.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'camera'
  return `${stem}_${estateStamp(capturedAt)}.jpg`
}

/** ", with the 2 other photos of this visit": the rest of a burst followed the fix. */
function visitWords(n: number): string {
  if (!n) return ''
  return n === 1 ? ', with the other photo of this visit' : `, with the ${n} other photos of this visit`
}

/** A phone with a share sheet: that is where "Save image" lives. */
const canShareFiles = () =>
  typeof navigator.share === 'function' && typeof navigator.canShare === 'function'
  && window.matchMedia('(pointer: coarse)').matches

export default function PhotoLightbox({
  photos,
  start = 0,
  backLabel,
  zIndex,
  onClose,
  onNotesChange,
  onKept,
  onFixed,
  onPeopleCleared,
  hasMore = false,
  onNeedMore,
  moreError,
}: {
  photos: LightboxPhoto[]
  start?: number
  backLabel: string
  zIndex?: number
  onClose: () => void
  /** A note was added or removed here: the photo's count now, for its tile and strips. */
  onNotesChange?: (imageId: string, count: number) => void
  /** A note kept a photo that was marked "nothing in it": it is an animal photo now. */
  onKept?: (imageId: string) => void
  /** "Wrong?" (or its Undo) changed what the photo is. A list drops a photo that no
   *  longer belongs in it when the viewer closes, never under it. */
  onFixed?: (imageId: string, fix: PhotoFix) => void
  /** An admin said nobody is in a frame of people (true), or took it back (false). */
  onPeopleCleared?: (imageId: string, cleared: boolean) => void
  /** The list has older photos than these; `onNeedMore` asks for the next page. */
  hasMore?: boolean
  onNeedMore?: () => void
  /** The next page didn't come, in words (morePhotosFailed); empty while it is asked again. */
  moreError?: string | null
}) {
  // The photo on show, by id: a list refreshed underneath (a new photo on top, a page
  // dropped) keeps showing the same photo instead of whatever took its place. When it
  // has left the list, the one now in its place, or the last.
  const [shownId, setShownId] = useState(() => photos[Math.min(Math.max(0, start), photos.length - 1)]?.id)
  const lastIdx = useRef(Math.min(Math.max(0, start), photos.length - 1))
  const found = photos.findIndex((p) => p.id === shownId)
  const idx = found >= 0 ? found : Math.max(0, Math.min(lastIdx.current, photos.length - 1))
  lastIdx.current = idx
  const im = photos[idx] as LightboxPhoto | undefined
  // Counts changed in this viewer, so paging back to a photo shows its new notes
  // even when the list that opened the viewer doesn't keep count itself.
  const [counts, setCounts] = useState<Record<string, number>>({})
  // Photos kept as animal photos by a note here, for the same reason.
  const [kept, setKept] = useState<Record<string, true>>({})
  // The note sheet is open: no paging, swiping or zooming until it is done, so a
  // note being written stays with its photo (PhotoNotes asks before throwing it away).
  const [sheetOpen, setSheetOpen] = useState(false)
  // "Wrong?": its sheet, the fixes made here (by photo), and the last one, for Undo.
  const [fixing, setFixing] = useState(false)
  const [fixes, setFixes] = useState<Record<string, PhotoFix>>({})
  const [change, setChange] = useState<Change | null>(null)
  const [undoing, setUndoing] = useState(false)
  const [changeErr, setChangeErr] = useState('')
  const [writer, setWriter] = useState(false)
  const [admin, setAdmin] = useState(false)
  // "Nobody in it?" on a frame of people: what was said here, by photo, and the last
  // one for its Undo.
  const [cleared, setCleared] = useState<Record<string, boolean>>({})
  const [peopleChange, setPeopleChange] = useState<{ id: string; cleared: boolean } | null>(null)
  const [peopleBusy, setPeopleBusy] = useState(false)
  const [peopleErr, setPeopleErr] = useState('')
  // Next was pressed at the end of what is loaded: go on once the next page is in.
  const [waitingMore, setWaitingMore] = useState(false)
  const holding = useRef(false)
  holding.current = sheetOpen || fixing
  const [imgReady, setImgReady] = useState(false)
  const [imgError, setImgError] = useState(false)
  const [saving, setSaving] = useState(false)
  const reduced = useReducedMotion()
  const [view, setView] = useState<View>(FIT)
  const viewRef = useRef(view)
  viewRef.current = view
  const stageRef = useRef<HTMLDivElement>(null)
  const imgRef = useRef<HTMLImageElement>(null)
  const swipe = useRef<{ x: number; t: number } | null>(null)
  // Every finger currently on the stage, by pointer id.
  const pointers = useRef(new Map<number, Pt>())
  // q0: the photo point (fit-scale px from its centre) that was under the fingers' midpoint.
  const pinch = useRef<{ d0: number; q0: Pt; s0: number } | null>(null)
  const pan = useRef<{ x: number; y: number; v0: View; moved: boolean } | null>(null)
  const lastTap = useRef<{ t: number; x: number; y: number } | null>(null)

  useEffect(() => {
    let live = true
    whoAmI().then((me) => {
      if (!live) return
      setWriter(me.role !== 'viewer')
      setAdmin(me.role === 'admin')
    }).catch(() => {})
    return () => { live = false }
  }, [])

  // Near the end of what is loaded, ask for the next page while this photo is looked at.
  const needMore = useRef(onNeedMore)
  needMore.current = onNeedMore
  useEffect(() => {
    if (hasMore && idx >= photos.length - 3) needMore.current?.()
  }, [idx, photos.length, hasMore])
  // Next pressed at the end: the next page came, so go on to it. None came: stop.
  useEffect(() => {
    if (!waitingMore) return
    if (idx < photos.length - 1) { setWaitingMore(false); step(1, true) } else if (!hasMore) setWaitingMore(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos.length, hasMore, waitingMore])
  // The page failed (no signal): stop waiting at once and say so at the end; the list
  // also gives up on one that never answers (its timeout), so this is a last resort.
  useEffect(() => { if (waitingMore && moreError) setWaitingMore(false) }, [waitingMore, moreError])
  useEffect(() => {
    if (!waitingMore) return
    const t = window.setTimeout(() => setWaitingMore(false), 25_000)
    return () => window.clearTimeout(t)
  }, [waitingMore])

  // "Changed to Fox. Undo" stays a while, then goes; a failed Undo stays until the next.
  useEffect(() => {
    if (!change || undoing || changeErr) return
    const t = window.setTimeout(() => setChange(null), 10_000)
    return () => window.clearTimeout(t)
  }, [change, undoing, changeErr])

  useEffect(() => {
    if (!peopleChange || peopleBusy || peopleErr) return
    const t = window.setTimeout(() => setPeopleChange(null), 10_000)
    return () => window.clearTimeout(t)
  }, [peopleChange, peopleBusy, peopleErr])

  // The photos either side load while this one is looked at, so a swipe on a weak
  // signal shows the next at once rather than "Loading photo…" (audit C-04).
  useEffect(() => {
    for (const near of [photos[idx + 1], photos[idx - 1]]) {
      if (!near) continue
      const img = new Image()
      img.decoding = 'async'
      img.src = imageUrl(near.file_url)
    }
  }, [idx, photos])

  // Keyboard: ← → to move, + − 0 to zoom. Escape belongs to Overlay, so that
  // every panel in the app answers it rather than only this one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (holding.current) return
      // Typing a note is not paging or zooming.
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (e.key === 'ArrowLeft') step(-1)
      if (e.key === 'ArrowRight') step(1)
      if (e.key === '+' || e.key === '=') setView((v) => zoomAt(v.s * 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '-') setView((v) => zoomAt(v.s / 1.5, { x: 0, y: 0 }, v, true))
      if (e.key === '0') setView(FIT)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, photos])

  // Wheel zoom wants preventDefault (ctrl+wheel would otherwise zoom the whole
  // page), and React registers wheel as passive, so this one is bound by hand.
  useEffect(() => {
    const st = stageRef.current
    if (!st) return
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
  }, [])

  /** Move through the photos, stopping at both ends, or asking for more at the end. */
  function step(d: number, force = false) {
    const i = idx + d
    if (!force && holding.current) return
    if (i >= photos.length && hasMore) {
      setWaitingMore(true)
      onNeedMore?.()
      return
    }
    if (i < 0 || i >= photos.length) return
    // The next photo fades in once it has actually decoded. Swapping src alone
    // gave a blank frame and then a jump as the stage resized to fit it.
    setImgReady(false)
    setImgError(false)
    setView(FIT)
    setShownId(photos[i].id)
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
    const el = imgRef.current
    if (!st || !el) return { ...v, s }
    const ox = Math.max(0, (el.offsetWidth * s - st.clientWidth) / 2)
    const oy = Math.max(0, (el.offsetHeight * s - st.clientHeight) / 2)
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
    if (holding.current) return
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

  // On a phone, the photo on show is also read into a file for the share sheet once
  // it has loaded (from the browser's cache, so it costs nothing more). The share has
  // to start inside the tap: it used to download the photo first, and on a slow link
  // the tap had expired by then and the phone opened the photo in a tab (C-29).
  const shareFile = useRef<{ id: string; file: File } | null>(null)
  useEffect(() => {
    if (!imgReady || !im || !canShareFiles()) return
    if (shareFile.current?.id === im.id) return
    let live = true
    const { id, file_url, camera, captured_at } = im
    fetch(imageUrl(file_url))
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((blob) => {
        if (live) shareFile.current = { id, file: new File([blob], downloadName(camera, captured_at), { type: blob.type || 'image/jpeg' }) }
      })
      .catch(() => {})
    return () => { live = false }
  }, [imgReady, im])

  // Nothing left to show (the list emptied under the viewer): close rather than crash.
  useEffect(() => { if (!im) onClose() }, [im, onClose])
  if (!im) return null

  function download() {
    if (saving || !im) return
    const src = imageUrl(im.file_url)
    const name = downloadName(im.camera, im.captured_at)
    const ready = shareFile.current?.id === im.id ? shareFile.current.file : null
    // On a phone the share sheet is where "Save Image" lives; a download link
    // on iOS opens the photo in a tab the user then has to find a way out of.
    if (ready && canShareFiles() && navigator.canShare({ files: [ready] })) {
      setSaving(true)
      navigator.share({ files: [ready], title: name })
        .catch(() => { /* dismissed, or refused: nothing to say */ })
        .finally(() => setSaving(false))
      return
    }
    // Everywhere else (and a phone still reading the photo): the server marks it as
    // an attachment and names it.
    const a = document.createElement('a')
    a.href = `${src}${src.includes('?') ? '&' : '?'}download=1`
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  /** What the photo is now, as this viewer knows it. */
  const current = (p: LightboxPhoto): PhotoFix => fixes[p.id] ?? {
    label: p.empty && kept[p.id] ? 'Animal' : p.label,
    species_id: p.species_id ?? null,
    empty: !!p.empty && !kept[p.id],
    hidden: false,
    fixed_by: p.fixed_by ?? null,
  }

  /** The photo is `fix` now, and the other photos of its visit what `fix.visit` says. */
  function apply(id: string, fix: Saved) {
    const { visit, ...mine } = fix
    setFixes((f) => ({ ...f, [id]: mine, ...Object.fromEntries(visit.map((v) => [v.id, v.fix])) }))
    onFixed?.(id, mine)
    for (const v of visit) onFixed?.(v.id, v.fix)
  }

  function fixed(id: string, fix: Saved, before: PhotoFix, choice: string) {
    apply(id, fix)
    setChange({ id, fix, before, choice })
    setChangeErr('')
  }

  /** Take the last fix back: "nothing here" is kept again; a species goes back to
   *  what it was (a hunter's earlier fix), or to what the AI said. */
  async function undo() {
    if (!change || undoing) return
    const { id, before, choice } = change
    setUndoing(true)
    setChangeErr('')
    try {
      let back: Saved
      if (choice === 'nothing') {
        await markEmpty(id, false)
        back = { ...before, empty: false, visit: [] }
      } else if (!before.empty && before.fixed_by && before.species_id) {
        back = await fixSpecies(id, before.species_id)
      } else {
        back = await undoFix(id)
      }
      apply(id, back)
      setChange(null)
    } catch (e) {
      const x = e as Failure
      setChangeErr(x.offline ? 'No signal, so it wasn’t undone. Try again.' : x.timeout
        ? 'No answer from the server, so it wasn’t undone. Try again.' : `It wasn’t undone. ${x.message}`)
    } finally {
      setUndoing(false)
    }
  }

  /** Say nobody is in this frame of people (a feeder read as a vehicle), or take it back. */
  async function clearPeople(id: string, yes: boolean) {
    if (peopleBusy) return
    setPeopleBusy(true)
    setPeopleErr('')
    try {
      await api(`/images/${id}/people`, { method: 'POST', body: JSON.stringify({ cleared: yes }), timeoutMs: 20_000 })
      setCleared((c) => ({ ...c, [id]: yes }))
      setPeopleChange({ id, cleared: yes })
      onPeopleCleared?.(id, yes)
    } catch (e) {
      const x = e as Failure
      setPeopleChange({ id, cleared: yes })  // what was asked for, for Try again
      setPeopleErr(x.offline ? 'No signal, so it wasn’t saved. Try again.' : x.timeout
        ? 'No answer from the server, so it wasn’t saved. Try again.' : `It wasn’t saved. ${x.message}`)
    } finally {
      setPeopleBusy(false)
    }
  }

  // Kept by a note here: no longer "No animal", and nothing for the sheet to keep.
  // A fix made here wins over what the list said.
  const now = current(im)
  const empty = now.empty
  const label = now.label
  const shownChange = change && change.id === im.id ? change : null
  const peopleFrame = !!im.people
  const nobody = !!cleared[im.id]
  const shownPeople = peopleChange && peopleChange.id === im.id ? peopleChange : null
  const when = new Date(im.captured_at).toLocaleString(undefined, {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })

  return (
    <Overlay
      label={`${im.camera} · Photo ${idx + 1} of ${photos.length}${hasMore ? '+' : ''}`}
      backLabel={backLabel}
      onClose={onClose}
      backdrop="rgba(0, 0, 0, 0.92)"
      zIndex={zIndex}
      style={{ flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 12 }}
      tools={
        // The things you do with a photo once it is big: put its name right, get
        // closer, and keep it.
        <>
          {peopleFrame && admin && !nobody && (
            <button className="ov-tool ov-tool--text" onClick={() => clearPeople(im.id, true)} disabled={peopleBusy}
              aria-label="Nobody in it? Put it back with the animal photos" title="Nobody in it (a feeder or a rock read as a vehicle)? Put it back with the animal photos">
              Nobody in it?
            </button>
          )}
          {writer && !peopleFrame && (
            <button className="ov-tool ov-tool--text" onClick={() => { setChange(null); setFixing(true) }}
              disabled={sheetOpen || fixing} aria-label="Wrong animal? Fix it" title="Wrong animal, or nothing in it? Fix it">
              Wrong?
            </button>
          )}
          <button
            className="ov-tool"
            onClick={toggleZoom}
            aria-label={view.s > 1 ? 'Fit photo to screen' : 'Zoom in'}
            title={view.s > 1 ? 'Fit to screen' : 'Zoom in. Double-tap or pinch works too'}
          >
            {view.s > 1 ? <MagnifyingGlassMinusIcon size={20} /> : <MagnifyingGlassPlusIcon size={20} />}
          </button>
          <button className="ov-tool" onClick={download} disabled={saving} aria-label="Save photo" title="Save photo">
            <DownloadSimpleIcon size={20} />
          </button>
        </>
      }
    >
      {(_close) => (
        <>
          {/* The stage and, beside or under it, the caption and the notes. The
              wrappers take no room of their own until a phone is on its side. */}
          <div className="lb-body">
            {/* A stage of fixed size. Photos come off the cameras at mixed aspect
                ratios, and letting each one set the frame meant the picture jumped
                around the screen as you paged through. */}
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
              {imgError && <div role="alert" className="lb-status">This photo did not load. Try the next one.</div>}
              {!imgReady && !imgError && <span role="status" className="lb-status">Loading photo…</span>}
              {shownChange && (
                <div className="lb-toast" role={changeErr ? 'alert' : 'status'}
                  onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                  <span>
                    {changeErr || (shownChange.choice === 'nothing'
                      ? 'Marked: nothing here. It leaves the photo lists.'
                      : `Changed to ${shownChange.fix.label}${visitWords(shownChange.fix.visit.length)}.${shownChange.fix.hidden ? ' That animal is hidden in Settings, so the photo leaves the lists.' : ''}`)}
                  </span>
                  <button type="button" className="lb-note-btn" onClick={undo} disabled={undoing}>{undoing ? 'Undoing…' : 'Undo'}</button>
                </div>
              )}
              {shownPeople && (
                <div className="lb-toast" role={peopleErr ? 'alert' : 'status'}
                  onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                  <span>
                    {peopleErr || (shownPeople.cleared
                      ? 'Marked: nobody in it. It goes back to the animal photos, for everyone.'
                      : 'Back with the people and vehicles.')}
                  </span>
                  {(shownPeople.cleared || peopleErr) && (
                    <button type="button" className="lb-note-btn" disabled={peopleBusy}
                      onClick={() => clearPeople(im.id, peopleErr ? shownPeople.cleared : false)}>
                      {peopleBusy ? 'Saving…' : peopleErr ? 'Try again' : 'Undo'}
                    </button>
                  )}
                </div>
              )}
              {waitingMore && <span role="status" className="lb-status lb-status--more">Loading older photos…</span>}
              {!waitingMore && moreError && hasMore && idx === photos.length - 1 && (
                <div className="lb-toast lb-more-err" role="alert"
                  onPointerDown={(e) => e.stopPropagation()} onPointerUp={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
                  <span>{moreError}</span>
                  <button type="button" className="lb-note-btn" onClick={() => step(1, true)}>Try again</button>
                </div>
              )}
              <img
                ref={imgRef}
                key={im.id}
                src={imageUrl(im.file_url)}
                alt={label}
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
            <div className="lb-side">
              <div className="lb-caption" onClick={(e) => e.stopPropagation()}>
                <b>{im.camera}</b>
                <span data-label>{label}</span>
                {now.fixed_by && <span className="lb-fixed-by">fixed by {now.fixed_by}</span>}
                <span style={{ opacity: 0.75 }}>{when}</span>
                <span style={{ opacity: 0.55, fontVariantNumeric: 'tabular-nums' }}>
                  {idx + 1} / {photos.length}{hasMore ? '+' : ''}
                </span>
              </div>
              {peopleFrame ? (
                <p className="lb-people-note">
                  Only admins see this photo. It never goes in the team’s photos, counts or alerts.
                </p>
              ) : <PhotoNotesPanel
                key={im.id}
                imageId={im.id}
                label={label}
                camera={im.camera}
                count={counts[im.id] ?? im.notes_count}
                empty={empty}
                onCount={(id, n) => {
                  setCounts((c) => ({ ...c, [id]: n }))
                  onNotesChange?.(id, n)
                }}
                onSheet={setSheetOpen}
                onKept={(id) => {
                  setKept((k) => ({ ...k, [id]: true }))
                  setFixes((f) => {
                    if (!f[id]) return f
                    const { [id]: _gone, ...rest } = f
                    return rest
                  })
                  onKept?.(id)
                }}
              />}
            </div>
          </div>
          {fixing && (
            <FixSheet
              imageId={im.id}
              label={label}
              camera={im.camera}
              speciesId={now.species_id}
              empty={empty}
              onClose={() => setFixing(false)}
              onFixed={(fix, choice) => {
                setFixing(false)
                fixed(im.id, fix, now, choice)
              }}
            />
          )}
          <button
            className="lb-nav lb-nav--prev"
            disabled={idx === 0 || sheetOpen || fixing}
            onClick={(e) => { e.stopPropagation(); step(-1) }}
            aria-label="Previous photo"
          >
            ‹
          </button>
          <button
            className="lb-nav lb-nav--next"
            disabled={(idx === photos.length - 1 && !hasMore) || sheetOpen || fixing || waitingMore}
            onClick={(e) => { e.stopPropagation(); step(1) }}
            aria-label="Next photo"
          >
            ›
          </button>
        </>
      )}
    </Overlay>
  )
}
