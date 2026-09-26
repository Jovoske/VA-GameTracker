import { BinocularsIcon } from '@phosphor-icons/react/dist/csr/Binoculars'
import { XIcon } from '@phosphor-icons/react/dist/csr/X'
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { api, whoAmI } from '../api'
import { NOTE_MAX, noteLine, type PhotoNote, type PhotoNotes } from '../notes'
import SwitchRow from './SwitchRow'

type Failure = Error & { offline?: boolean; timeout?: boolean; status?: number }
const TIMEOUT_MS = 20_000

function failed(e: unknown, what: string): string {
  const x = e as Failure
  if (x.offline) return `No signal, so ${what}.`
  if (x.timeout) return `No answer from the server, so ${what}.`
  return `${x.message}`
}

/**
 * The notes under a photo in the viewer, and the "Worth a look" button.
 *
 * Who marked it and when, oldest first: "Pedro · 21:40 · Big boar, third night
 * running". Your own notes (or anyone's, for an admin) have a remove button that
 * asks first. Viewers read them; the button is for members and admins. `count`
 * is what the photo's list says it has: at 0 nothing is asked of the server, so
 * paging through a gallery doesn't cost a call per photo.
 */
export default function PhotoNotesPanel({ imageId, label, camera, count, onCount }: {
  imageId: string
  label: string
  camera: string
  count: number | undefined
  /** After a note is added or removed: how many the photo has now. */
  onCount: (imageId: string, n: number) => void
}) {
  const [data, setData] = useState<PhotoNotes | null>(count === 0 ? { image_id: imageId, can_add: false, notes: [] } : null)
  const [err, setErr] = useState('')
  const [writer, setWriter] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [removing, setRemoving] = useState(false)
  const [said, setSaid] = useState<{ text: string; err: boolean } | null>(null)
  const request = useRef(0)

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
      .catch((e) => { if (id === request.current) setErr(failed(e, 'the notes didn’t load')) })
  }
  useEffect(() => {
    if (count !== 0) load()
    return () => { request.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId])

  // "Marked" is news for a few seconds; a failure stays until the next try.
  useEffect(() => {
    if (!said || said.err) return
    const t = window.setTimeout(() => setSaid(null), 6000)
    return () => window.clearTimeout(t)
  }, [said])

  async function remove(n: PhotoNote) {
    setRemoving(true)
    setSaid(null)
    try {
      const r = await api<PhotoNotes>(`/photo-notes/${n.id}`, { method: 'DELETE', timeoutMs: TIMEOUT_MS })
      setData(r)
      onCount(imageId, r.notes.length)
      setSaid({ err: false, text: 'Note removed.' })
      setConfirm(null)
    } catch (e) {
      const x = e as Failure
      if (x.status === 404) { load(); setConfirm(null); setSaid({ err: false, text: 'That note was already gone.' }); return }
      setSaid({ err: true, text: failed(e, 'the note is still there') })
    } finally {
      setRemoving(false)
    }
  }

  const notes = data?.notes ?? []
  return (
    <div className="lb-notes" onClick={(e) => e.stopPropagation()}>
      <div className="lb-notes-list" aria-label="Notes on this photo">
        {!data && !err && <p className="lb-notes-quiet" role="status">Loading notes…</p>}
        {err && !data && <p className="lb-notes-quiet" role="alert">{err} <button type="button" className="lb-notes-link" onClick={load}>Try again</button></p>}
        {data && notes.length === 0 && <p className="lb-notes-quiet">{writer ? 'No notes yet. Seen something? Mark it for the team.' : 'No notes on this photo.'}</p>}
        {notes.map((n) => confirm === n.id ? (
          <div key={n.id} className="lb-note lb-note--confirm" role="group" aria-label="Remove this note?">
            <span className="lb-note-text">{n.mine ? 'Remove your note?' : `Remove ${n.name}’s note?`}</span>
            <button type="button" className="lb-note-btn lb-note-btn--danger" disabled={removing} onClick={() => remove(n)}>{removing ? 'Removing…' : 'Remove'}</button>
            <button type="button" className="lb-note-btn" disabled={removing} onClick={() => setConfirm(null)}>Keep</button>
          </div>
        ) : (
          <div key={n.id} className="lb-note">
            <span className="lb-note-text">{noteLine(n)}</span>
            {n.can_remove && <button type="button" className="lb-note-x" aria-label={n.mine ? 'Remove your note' : `Remove ${n.name}’s note`} onClick={() => { setSaid(null); setConfirm(n.id) }}><XIcon size={16} /></button>}
          </div>
        ))}
      </div>
      {said && <p className={`lb-notes-said${said.err ? ' lb-notes-said--err' : ''}`} role={said.err ? 'alert' : 'status'}>{said.text}</p>}
      {writer && (
        <button type="button" className="lb-worth" onClick={() => { setSaid(null); setSheet(true) }}>
          <BinocularsIcon size={22} aria-hidden="true" /> Worth a look
        </button>
      )}
      {sheet && (
        <NoteSheet imageId={imageId} label={label} camera={camera} onClose={() => setSheet(false)}
          onSaved={(r, told, tell) => {
            setData(r)
            setErr('')
            onCount(imageId, r.notes.length)
            setSheet(false)
            const who = told === 1 ? '1 person' : `${told} people`
            setSaid({
              err: false,
              text: `Marked worth a look.${tell ? told ? ` Told ${who}.` : ' Nobody else has alerts on, so no one was told.' : ''}`,
            })
          }} />
      )}
    </div>
  )
}

/** How far the on-screen keyboard covers the bottom of the screen, so the sheet can sit above it. */
function useKeyboardLift(): number {
  const [lift, setLift] = useState(0)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const on = () => setLift(Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop)))
    on()
    vv.addEventListener('resize', on)
    vv.addEventListener('scroll', on)
    return () => { vv.removeEventListener('resize', on); vv.removeEventListener('scroll', on) }
  }, [])
  return lift
}

/**
 * The small sheet behind "Worth a look": an optional note (140 at most, counted as
 * you type), a "Tell the team" switch that starts off, and Save.
 */
function NoteSheet({ imageId, label, camera, onClose, onSaved }: {
  imageId: string
  label: string
  camera: string
  onClose: () => void
  onSaved: (r: PhotoNotes, told: number, tell: boolean) => void
}) {
  const [text, setText] = useState('')
  const [tell, setTell] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const lift = useKeyboardLift()
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => { root.current?.focus({ preventScroll: true }) }, [])

  async function save() {
    if (saving) return
    setSaving(true)
    setErr('')
    try {
      const r = await api<PhotoNotes & { told: number }>(`/images/${imageId}/notes`, {
        method: 'POST', body: JSON.stringify({ text: text.trim() || null, tell_team: tell }), timeoutMs: TIMEOUT_MS,
      })
      onSaved(r, r.told, tell)
    } catch (e) {
      setErr(`${failed(e, 'it didn’t save')} Your note is still here; try again.`)
      setSaving(false)
    }
  }

  // Keys typed here are the note's, not the viewer's: arrows move the caret, not the
  // photo, and Escape closes this sheet only. Tab still goes round the panel.
  function onKey(e: ReactKeyboardEvent) {
    if (e.key === 'Tab') return
    e.stopPropagation()
    if (e.key === 'Escape') { e.preventDefault(); if (!saving) onClose() }
  }

  const left = NOTE_MAX - text.length
  return (
    <div ref={root} className="lb-sheet" role="dialog" aria-label="Worth a look" tabIndex={-1}
      style={{ bottom: lift }} onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()} onKeyDown={onKey}>
      <div className="lb-sheet-head">
        <div className="lb-sheet-title">
          <h2>Worth a look</h2>
          <p>{label} · {camera}</p>
        </div>
        <button type="button" className="lb-sheet-x" aria-label="Cancel" onClick={onClose} disabled={saving}><XIcon size={20} /></button>
      </div>
      <label className="lb-sheet-label" htmlFor={`note-${imageId}`}>Note for the team <span>(optional)</span></label>
      <textarea id={`note-${imageId}`} className="input lb-sheet-text" rows={2} maxLength={NOTE_MAX} value={text}
        placeholder="Big boar, third night running" onChange={(e) => setText(e.target.value)} />
      <p className={`lb-sheet-count${left <= 10 ? ' lb-sheet-count--low' : ''}`} aria-live="polite">{text.length} / {NOTE_MAX}</p>
      <SwitchRow label="Tell the team" note="One alert to everyone who has alerts on" on={tell} onChange={setTell} disabled={saving} />
      {err && <p className="lb-sheet-err" role="alert">{err}</p>}
      <button type="button" className="btn lb-sheet-save" onClick={save} disabled={saving}>
        {saving ? 'Saving…' : 'Save'}
        {saving && <span className="btn-progress" aria-hidden="true" />}
      </button>
    </div>
  )
}
