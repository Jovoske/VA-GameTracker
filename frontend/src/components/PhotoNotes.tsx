import { BinocularsIcon } from '@phosphor-icons/react/dist/csr/Binoculars'
import { XIcon } from '@phosphor-icons/react/dist/csr/X'
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { api, whoAmI } from '../api'
import { NOTE_MAX, newNoteId, noteLine, type NoteSaved, type PhotoNote, type PhotoNotes } from '../notes'
import { t } from '../i18n'
import SwitchRow from './SwitchRow'

type Failure = Error & { offline?: boolean; timeout?: boolean; status?: number; code?: string }
const TIMEOUT_MS = 20_000

function failed(e: unknown, what: string): string {
  const x = e as Failure
  if (x.offline) return t('notes.failNoSignal', { what })
  if (x.timeout) return t('notes.failTimeout', { what })
  return `${x.message}`
}

/** The server's "this photo is marked nothing in it": by its code, or its English words
 *  from a server that sends no code. */
const emptyFrame = (x: Failure) => x.status === 409 && (x.code === 'empty_frame' || /nothing in it/.test(x.message))

/**
 * The notes under a photo in the viewer, and the "Worth a look" button.
 *
 * Who marked it and when, oldest first: "Pedro · 21:40 · Big boar, third night
 * running". Your own notes (or anyone's, for an admin) have a remove button that
 * asks first. Viewers read them; the button is for members and admins. `count`
 * is what the photo's list says it has: at 0 nothing is asked of the server, so
 * paging through a gallery doesn't cost a call per photo.
 *
 * A photo marked "nothing in it" (Cameras shows those on request) is where a hunter
 * finds the deer the detector missed. A note on it keeps it as an animal photo, and
 * the sheet says so before Save: the team can't open a photo the app hides.
 */
export default function PhotoNotesPanel({ imageId, label, camera, count, empty, onCount, onSheet, onKept }: {
  imageId: string
  label: string
  camera: string
  count: number | undefined
  /** Marked "nothing in it": saving a note keeps it as an animal photo. */
  empty?: boolean
  /** After a note is added or removed: how many the photo has now. */
  onCount: (imageId: string, n: number) => void
  /** The note sheet opened or closed. While it is open the viewer holds still. */
  onSheet?: (open: boolean) => void
  /** A note kept a photo that was marked "nothing in it". */
  onKept?: (imageId: string) => void
}) {
  const [data, setData] = useState<PhotoNotes | null>(count === 0 ? { image_id: imageId, can_add: false, notes: [] } : null)
  const [err, setErr] = useState('')
  const [writer, setWriter] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [said, setSaid] = useState<{ text: string; err: boolean } | null>(null)
  const request = useRef(0)
  const worth = useRef<HTMLButtonElement>(null)
  const sheetOpen = useRef(false)
  const onSheetRef = useRef(onSheet)
  onSheetRef.current = onSheet

  useEffect(() => {
    let live = true
    whoAmI().then((me) => { if (live) setWriter(me.role !== 'viewer') }).catch(() => {})
    return () => { live = false }
  }, [])

  function load() {
    const id = ++request.current
    setErr('')
    api<PhotoNotes>(`/images/${imageId}/notes`, { timeoutMs: TIMEOUT_MS })
      .then((r) => { if (id === request.current) setData(r) })
      .catch((e) => { if (id === request.current) setErr(failed(e, t('notes.what.didntLoad'))) })
  }
  useEffect(() => {
    if (count !== 0) load()
    return () => { request.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId])

  // Gone with the sheet still open (the photo left the list): let the viewer move again.
  useEffect(() => () => { if (sheetOpen.current) onSheetRef.current?.(false) }, [])

  // "Marked" is news for a few seconds; a failure stays until the next try.
  useEffect(() => {
    if (!said || said.err) return
    const t = window.setTimeout(() => setSaid(null), 6000)
    return () => window.clearTimeout(t)
  }, [said])

  function openSheet(open: boolean) {
    sheetOpen.current = open
    setSheet(open)
    onSheet?.(open)
    // Back to the button that opened it, for a keyboard or a screen reader.
    if (!open) requestAnimationFrame(() => worth.current?.focus({ preventScroll: true }))
  }

  function saved(r: PhotoNotes, text: string) {
    setData(r)
    setErr('')
    onCount(imageId, r.notes.length)
    openSheet(false)
    setSaid({ err: false, text })
  }

  async function remove(n: PhotoNote) {
    setRemoving(true)
    setSaid(null)
    try {
      const r = await api<PhotoNotes>(`/photo-notes/${n.id}`, { method: 'DELETE', timeoutMs: TIMEOUT_MS })
      setData(r)
      onCount(imageId, r.notes.length)
      setSaid({ err: false, text: t('notes.removed') })
      setConfirm(null)
    } catch (e) {
      const x = e as Failure
      if (x.status === 404) { load(); setConfirm(null); setSaid({ err: false, text: t('notes.alreadyGone') }); return }
      setSaid({ err: true, text: failed(e, t('notes.what.stillThere')) })
    } finally {
      setRemoving(false)
    }
  }

  const notes = data?.notes ?? []
  const quiet = !writer ? t('notes.none')
    : empty ? t('notes.noneEmpty')
      : t('notes.noneYet')
  return (
    <div className="lb-notes" onClick={(e) => e.stopPropagation()}>
      <div className="lb-notes-list" aria-label={t('notes.listLabel')}>
        {!data && !err && <p className="lb-notes-quiet" role="status">{t('notes.loading')}</p>}
        {err && !data && <p className="lb-notes-quiet" role="alert">{err} <button type="button" className="lb-notes-link" onClick={load}>{t('common.tryAgain')}</button></p>}
        {data && notes.length === 0 && <p className="lb-notes-quiet">{quiet}</p>}
        {notes.map((n) => confirm === n.id ? (
          <div key={n.id} className="lb-note lb-note--confirm" role="group" aria-label={t('notes.removeThis')}>
            <span className="lb-note-text">{n.mine ? t('notes.removeYours') : t('notes.removeTheirs', { name: n.name })}</span>
            <button type="button" className="lb-note-btn lb-note-btn--danger" disabled={removing} onClick={() => remove(n)}>{removing ? t('common.removing') : t('common.remove')}</button>
            <button type="button" className="lb-note-btn" disabled={removing} onClick={() => setConfirm(null)}>{t('common.keep')}</button>
          </div>
        ) : (
          <div key={n.id} className="lb-note">
            <span className="lb-note-text">{noteLine(n)}</span>
            {n.can_remove && <button type="button" className="lb-note-x" aria-label={n.mine ? t('notes.removeYoursLabel') : t('notes.removeTheirsLabel', { name: n.name })} onClick={() => { setSaid(null); setConfirm(n.id) }}><XIcon size={16} /></button>}
          </div>
        ))}
      </div>
      {said && <p className={`lb-notes-said${said.err ? ' lb-notes-said--err' : ''}`} role={said.err ? 'alert' : 'status'}>{said.text}</p>}
      {writer && (
        <button ref={worth} type="button" className="lb-worth" onClick={() => { setSaid(null); openSheet(true) }}>
          <BinocularsIcon size={22} aria-hidden="true" /> {t('notes.worthALook')}
        </button>
      )}
      {sheet && (
        <NoteSheet imageId={imageId} label={label} camera={camera} empty={!!empty} onClose={() => openSheet(false)}
          onSaved={(r, tell, kept) => {
            if (kept) onKept?.(imageId)
            saved(r, `${kept ? t('notes.keptMarked') : t('notes.marked')}${tell ? ` ${toldWords(r.told, r.muted ?? 0, camera)}` : ''}`)
          }}
          onFound={(r, tell, kept) => {
            if (kept) onKept?.(imageId)
            saved(r, `${t('notes.slowSaved')}${tell ? ` ${t('notes.everyoneTold')}` : ''}`)
          }} />
      )}
    </div>
  )
}

/** Who "Tell the team" reached, and when nobody, why: nobody else has alerts on, or
 * everyone who has muted this camera. */
function toldWords(told: number, muted: number, camera: string): string {
  if (told) return `${t('notes.told', { count: told })}${muted ? ` ${t('notes.muted', { count: muted, camera })}` : ''}`
  if (muted) return t('notes.allMuted', { camera })
  return t('notes.nobody')
}

/** How far the on-screen keyboard covers the bottom of the screen, and how much is left
 * above it, so the sheet can sit above the keyboard and never run off the top. */
function useKeyboardLift(): { lift: number; room: number | null } {
  const [at, setAt] = useState<{ lift: number; room: number | null }>({ lift: 0, room: null })
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const on = () => setAt({ lift: Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)), room: Math.round(vv.height) })
    on()
    vv.addEventListener('resize', on)
    vv.addEventListener('scroll', on)
    return () => { vv.removeEventListener('resize', on); vv.removeEventListener('scroll', on) }
  }, [])
  return at
}

/**
 * The small sheet behind "Worth a look": an optional note (140 at most, counted as
 * you type), a "Tell the team" switch that starts off, and Save.
 *
 * It holds the viewer still until it is done: a dim layer over the photo takes the
 * taps, the viewer stops paging (PhotoLightbox), and the phone's Back closes this
 * sheet rather than the photo. With words typed, leaving any way but Save asks
 * first, so a note is never lost without a word.
 *
 * The note's id is made here, once. On a weak signal the save can land while its
 * answer doesn't; the sheet then looks for the note before offering to try again,
 * and a second try is the same note on the server, never a copy or a second alert.
 */
function NoteSheet({ imageId, label, camera, empty, onClose, onSaved, onFound }: {
  imageId: string
  label: string
  camera: string
  empty: boolean
  onClose: () => void
  onSaved: (r: NoteSaved, tell: boolean, kept: boolean) => void
  /** It saved after all: the answer was lost, the note is on the server. */
  onFound: (r: PhotoNotes, tell: boolean, kept: boolean) => void
}) {
  const [text, setText] = useState('')
  const [tell, setTell] = useState(false)
  const [busy, setBusy] = useState<'saving' | 'checking' | null>(null)
  const [err, setErr] = useState('')
  const [asking, setAsking] = useState(false)
  // Starts as the viewer knew it; a server that knows better (another hunter just
  // marked it empty, or a gallery didn't say) turns it on.
  const [keep, setKeep] = useState(empty)
  const { lift, room } = useKeyboardLift()
  const root = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  const noteId = useRef(newNoteId())
  const live = useRef(true)
  const done = useRef(false)
  // What the listeners on window need, as it is now.
  const state = useRef({ text, busy })
  state.current = { text, busy }

  useEffect(() => {
    live.current = true
    root.current?.focus({ preventScroll: true })
    return () => { live.current = false }
  }, [])

  /** Gone for good (saved, or thrown away): take this sheet's step off the history too. */
  function finish(after: () => void) {
    done.current = true
    if (window.history.state?.lbNote === noteId.current) window.history.back()
    after()
  }

  /** Asked to go without saving: the dim layer, Escape, Back or ✕. Words typed? Ask. */
  function leave() {
    if (state.current.busy) return
    if (state.current.text.trim()) { setAsking(true); return }
    finish(onClose)
  }
  const leaveRef = useRef(leave)
  leaveRef.current = leave

  // The phone's Back closes this sheet, not the photo under it: the sheet is one step
  // in the history of its own (the viewer's step stays, so the viewer ignores it).
  useEffect(() => {
    const mark = noteId.current
    if (window.history.state?.lbNote !== mark) {
      window.history.pushState({ ...(window.history.state ?? {}), lbNote: mark }, '')
    }
    const onPop = () => {
      if (done.current || window.history.state?.lbNote === mark) return
      if (state.current.busy || state.current.text.trim()) {
        // Not yet: put the step back, and ask (or let the save finish).
        window.history.pushState({ ...(window.history.state ?? {}), lbNote: mark }, '')
        if (!state.current.busy) setAsking(true)
        return
      }
      done.current = true
      onClose()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Escape and Tab belong to this sheet while it is open, wherever focus is: Escape
  // leaves it (asking first), Tab goes round its own controls. Caught on the way down,
  // before the viewer's Overlay hears them and closes the photo.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        leaveRef.current()
      } else if (e.key === 'Tab') {
        const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled), textarea, [tabindex="0"]') ?? [])
          .filter((el) => el.getClientRects().length > 0)
        if (!controls.length) return
        e.preventDefault()
        e.stopPropagation()
        const at = controls.indexOf(document.activeElement as HTMLElement)
        const next = at < 0 ? (e.shiftKey ? controls.length - 1 : 0) : (at + (e.shiftKey ? -1 : 1) + controls.length) % controls.length
        controls[next]?.focus()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  async function save() {
    if (busy) return
    setBusy('saving')
    setErr('')
    setAsking(false)
    const kept = keep
    try {
      const r = await api<NoteSaved>(`/images/${imageId}/notes`, {
        method: 'POST',
        body: JSON.stringify({ id: noteId.current, text: text.trim() || null, tell_team: tell, keep: kept }),
        timeoutMs: TIMEOUT_MS,
      })
      if (!live.current) return
      finish(() => onSaved(r, tell, kept))
    } catch (e) {
      if (!live.current) return
      const x = e as Failure
      if (x.timeout || x.offline) {
        // The note may be on the server with only its answer lost: look before saying.
        setBusy('checking')
        setErr(x.timeout ? t('notes.maybeTimeout') : t('notes.maybeDropped'))
        try {
          const now = await api<PhotoNotes>(`/images/${imageId}/notes`, { timeoutMs: TIMEOUT_MS })
          if (!live.current) return
          if (now.notes.some((n) => n.id === noteId.current)) { finish(() => onFound(now, tell, kept)); return }
          setErr(t('notes.didntSave'))
        } catch {
          if (!live.current) return
          setErr(x.timeout ? t('notes.stillNoAnswer') : t('notes.stillNoSignal'))
        }
      } else if (emptyFrame(x) && !kept) {
        setKeep(true)
        setErr(t('notes.detectorEmpty'))
      } else {
        setErr(t('notes.stillHere', { why: x.message }))
      }
      setBusy(null)
    }
  }

  // Keys typed here are the note's, not the viewer's: arrows move the caret, not the
  // photo. Escape and Tab are handled above, for the whole sheet.
  function onKey(e: ReactKeyboardEvent) {
    if (e.key !== 'Tab' && e.key !== 'Escape') e.stopPropagation()
  }

  const left = NOTE_MAX - text.length
  return (
    <>
      <div className="lb-scrim" aria-hidden="true" onClick={(e) => { e.stopPropagation(); leave() }} onPointerDown={(e) => e.stopPropagation()} />
      <div ref={root} className="lb-sheet" role="dialog" aria-modal="true" aria-label={t('notes.worthALook')} tabIndex={-1}
        style={{ bottom: lift, maxHeight: room ? room - 8 : undefined }}
        onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <div className="lb-sheet-head">
          <div className="lb-sheet-title">
            <h2>{t('notes.worthALook')}</h2>
            <p>{label} · {camera}</p>
          </div>
          <button type="button" className="lb-sheet-x" aria-label={t('common.cancel')} onClick={leave} disabled={!!busy}><XIcon size={20} /></button>
        </div>
        {keep && <p className="lb-sheet-keep">{t('notes.keepHint')}</p>}
        <label className="lb-sheet-label" htmlFor={`note-${imageId}`}>{t('notes.noteForTeam')} <span>{t('notes.optional')}</span></label>
        <textarea ref={area} id={`note-${imageId}`} className="input lb-sheet-text" rows={2} maxLength={NOTE_MAX} value={text}
          placeholder={t('notes.placeholder')} onChange={(e) => { setText(e.target.value); setAsking(false) }}
          // The keyboard coming up can hide it inside a short sheet (a phone on its side).
          onFocus={(e) => { const el = e.currentTarget; window.setTimeout(() => el.scrollIntoView({ block: 'nearest' }), 300) }} />
        <p className={`lb-sheet-count${left <= 10 ? ' lb-sheet-count--low' : ''}`} aria-live="polite">{text.length} / {NOTE_MAX}</p>
        <SwitchRow label={t('notes.tellTeam')} note={t('notes.tellTeamNote')} on={tell} onChange={setTell} disabled={!!busy} />
        {err && <p className="lb-sheet-err" role="alert">{err}</p>}
        {asking ? (
          <div className="lb-sheet-ask" role="group" aria-label={t('notes.throwAway')}>
            <p>{t('notes.throwAway')}</p>
            <button type="button" className="lb-note-btn" autoFocus onClick={() => { setAsking(false); area.current?.focus() }}>{t('notes.keepWriting')}</button>
            <button type="button" className="lb-note-btn lb-note-btn--danger" onClick={() => finish(onClose)}>{t('notes.throwAwayBtn')}</button>
          </div>
        ) : (
          <button type="button" className="btn lb-sheet-save" onClick={save} disabled={!!busy}>
            {busy === 'checking' ? t('common.checking') : busy ? t('common.saving') : keep ? t('notes.keepAndSave') : t('common.save')}
            {busy && <span className="btn-progress" aria-hidden="true" />}
          </button>
        )}
      </div>
    </>
  )
}
