import { CheckIcon } from '@phosphor-icons/react/dist/csr/Check'
import { XIcon } from '@phosphor-icons/react/dist/csr/X'
import { useEffect, useRef, useState } from 'react'
import { api, type Failure } from '../api'
import { type Key, cap, t } from '../i18n'

/**
 * "Wrong?" in the photo viewer: say what the animal really is, or that there is
 * nothing in the photo (a false alarm). Members and admins; viewers never see it.
 *
 * The answer is the hunter's: the AI never changes it back, and every list and
 * count (Photos, Animals, the map, the forecast) reads the species from the photo,
 * so they all follow at once. A burst is one animal, so the other photos of the
 * visit that read as the old name follow too (`visit`). The viewer shows the new
 * name straight away with an Undo, and the list under it drops a photo that no
 * longer belongs there once the viewer closes, never while it is open.
 */

/** What a photo is after a fix, as the viewer and the lists under it show it. */
export type PhotoFix = {
  label: string
  species_id: string | null
  /** Marked "nothing here": it leaves the photo lists. */
  empty: boolean
  /** One of the animals hidden in Settings: it leaves the photo lists too. */
  hidden: boolean
  fixed_by: string | null
}

/** Another photo of the same visit, as it is after the fix. */
export type VisitFix = { id: string; fix: PhotoFix }
/** A fix, and the other photos of the burst that followed it (or went back with its Undo). */
export type Saved = PhotoFix & { visit: VisitFix[] }

/** What the server answers after a fix (routes_images.set_species / undo_species). */
type Fixed = PhotoFix & { image_id: string; group_size: number | null; visit?: Fixed[] }

const plain = (r: Fixed): PhotoFix =>
  ({ label: r.label, species_id: r.species_id, empty: r.empty, hidden: r.hidden, fixed_by: r.fixed_by })
const saved = (r: Fixed): Saved =>
  ({ ...plain(r), visit: (r.visit ?? []).map((v) => ({ id: v.image_id, fix: plain(v) })) })

export type Choice = { id: string; name: string; hidden: boolean; likely: boolean; big_game: boolean; seen: number }

const TIMEOUT_MS = 20_000
// The last list, shown at once when the sheet opens while it is asked again: an admin
// may have renamed an animal since (Settings), here or on another phone.
let lastChoices: Choice[] | null = null
let asking: Promise<Choice[]> | null = null

/** The animals a photo can be said to show, as the server has them now. */
export function loadChoices(): Promise<Choice[]> {
  if (!asking) {
    asking = api<Choice[]>('/species/choices', { timeoutMs: TIMEOUT_MS })
      .then((c) => { lastChoices = c; return c })
      .finally(() => { asking = null })
  }
  return asking
}

/** An animal was renamed or hidden in Settings: the saved list is out of date. */
export function resetChoices(): void {
  lastChoices = null
}

function failed(e: unknown, what: Key): string {
  const x = e as Failure
  if (x.offline) return t('book.failNoSignal', { what: t(what) })
  if (x.timeout) return t('book.failTimeout', { what: t(what) })
  return t('harvest.failOther', { reason: x.message || t('common.wentWrong'), what: cap(t(what)) })
}

/** Say the photo shows `speciesId`. */
export async function fixSpecies(imageId: string, speciesId: string): Promise<Saved> {
  return saved(await api<Fixed>(`/images/${imageId}/species`, {
    method: 'POST', body: JSON.stringify({ species_id: speciesId }), timeoutMs: TIMEOUT_MS,
  }))
}

/** Mark it "nothing here", or keep it again (Undo). */
export async function markEmpty(imageId: string, empty: boolean): Promise<void> {
  await api(`/images/${imageId}/flag`, { method: 'POST', body: JSON.stringify({ is_empty: empty }), timeoutMs: TIMEOUT_MS })
}

/** Put back what the AI said. */
export async function undoFix(imageId: string): Promise<Saved> {
  return saved(await api<Fixed>(`/images/${imageId}/species`, { method: 'DELETE', timeoutMs: TIMEOUT_MS }))
}

/**
 * The sheet: the likely animals as big buttons (the big game, then what the cameras
 * have seen), the rest behind "More animals", and "Nothing here" on its own at the
 * bottom. One tap saves. It holds the viewer still while it is open, and the phone's
 * Back, Escape and the dim layer close it, not the photo.
 */
export function FixSheet({ imageId, label, camera, speciesId, empty, onClose, onFixed }: {
  imageId: string
  label: string
  camera: string
  /** What the photo is now, to mark it on the list. */
  speciesId: string | null
  empty: boolean
  onClose: () => void
  /** Saved: what it is now, and the choice made ("nothing" for Nothing here). */
  onFixed: (fix: Saved, choice: string) => void
}) {
  const [list, setList] = useState<Choice[] | null>(lastChoices)
  const [loadErr, setLoadErr] = useState('')
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const root = useRef<HTMLDivElement>(null)
  const live = useRef(true)
  const done = useRef(false)
  const mark = useRef(`fix-${imageId}-${Date.now()}`)
  const busyRef = useRef(busy)
  busyRef.current = busy

  // Asked again every time; the list from last time shows meanwhile, and stays if the
  // signal is gone (it is a list of animals, not something that goes stale in a night).
  function load() {
    setLoadErr('')
    loadChoices()
      .then((c) => { if (live.current && !busyRef.current) setList(c) })
      .catch((e) => { if (live.current && !lastChoices) setLoadErr(failed(e, 'harvest.what.list')) })
  }
  useEffect(() => {
    live.current = true
    load()
    root.current?.focus({ preventScroll: true })
    return () => { live.current = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Gone (saved, or closed): take this sheet's step off the history too. */
  function finish(after: () => void) {
    done.current = true
    if (window.history.state?.lbFix === mark.current) window.history.back()
    after()
  }
  const leave = () => { if (!busyRef.current) finish(onClose) }
  const leaveRef = useRef(leave)
  leaveRef.current = leave

  // The phone's Back closes this sheet, not the photo under it (as the note sheet does).
  useEffect(() => {
    const me = mark.current
    if (window.history.state?.lbFix !== me) window.history.pushState({ ...(window.history.state ?? {}), lbFix: me }, '')
    const onPop = () => {
      if (done.current || window.history.state?.lbFix === me) return
      if (busyRef.current) {
        window.history.pushState({ ...(window.history.state ?? {}), lbFix: me }, '')
        return
      }
      done.current = true
      onClose()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Escape and Tab belong to the sheet while it is open, before the viewer hears them.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        leaveRef.current()
      } else if (e.key === 'Tab') {
        const controls = Array.from(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled)') ?? [])
          .filter((el) => el.getClientRects().length > 0)
        if (!controls.length) return
        e.preventDefault()
        e.stopPropagation()
        const at = controls.indexOf(document.activeElement as HTMLElement)
        const next = at < 0 ? (e.shiftKey ? controls.length - 1 : 0) : (at + (e.shiftKey ? -1 : 1) + controls.length) % controls.length
        controls[next]?.focus()
      } else {
        // Arrows and + - 0 are not the viewer's while the sheet is open.
        e.stopPropagation()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  async function choose(choice: string) {
    if (busy) return
    if (choice === 'nothing' ? empty : choice === speciesId && !empty) { leave(); return }
    setBusy(choice)
    setErr('')
    try {
      let fix: Saved
      if (choice === 'nothing') {
        await markEmpty(imageId, true)
        fix = { label: t('fix.nothingHere'), species_id: null, empty: true, hidden: false, fixed_by: null, visit: [] }
      } else {
        fix = await fixSpecies(imageId, choice)
      }
      if (!live.current) return
      finish(() => onFixed(fix, choice))
    } catch (e) {
      if (!live.current) return
      setErr(failed(e, 'fix.what.notChanged'))
      setBusy(null)
    }
  }

  const shown = list ? (more ? list : list.filter((c) => c.likely || c.id === speciesId)) : []
  const rest = list ? list.length - list.filter((c) => c.likely || c.id === speciesId).length : 0
  return (
    <>
      <div className="lb-scrim" aria-hidden="true" onClick={(e) => { e.stopPropagation(); leave() }} onPointerDown={(e) => e.stopPropagation()} />
      <div ref={root} className="lb-sheet lb-fix" role="dialog" aria-modal="true" aria-label={t('fix.label')} tabIndex={-1}
        onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
        <div className="lb-sheet-head">
          <div className="lb-sheet-title">
            <h2>{t('fix.title')}</h2>
            <p>{t('fix.now', { label, camera })}</p>
          </div>
          <button type="button" className="lb-sheet-x" aria-label={t('common.cancel')} onClick={leave} disabled={!!busy}><XIcon size={20} /></button>
        </div>
        {!list && !loadErr && <p className="lb-sheet-keep" role="status">{t('harvest.loadingAnimals')}</p>}
        {loadErr && (
          <p className="lb-sheet-err" role="alert">{loadErr}{' '}
            <button type="button" className="lb-notes-link lb-fix-link" onClick={load}>{t('common.tryAgain')}</button>
          </p>
        )}
        {list && (
          <div className="lb-fix-grid" role="group" aria-label={t('fix.itsA')}>
            {shown.map((c) => {
              const now = c.id === speciesId && !empty
              return (
                <button key={c.id} type="button" className="lb-fix-choice" aria-pressed={now} disabled={!!busy}
                  data-species={c.id} onClick={() => choose(c.id)}>
                  {now && <CheckIcon size={16} weight="bold" aria-hidden="true" />}
                  <span>{busy === c.id ? t('common.saving') : c.name}</span>
                  {c.hidden && <small>{t('fix.hidden')}</small>}
                </button>
              )
            })}
          </div>
        )}
        {list && rest > 0 && (
          <button type="button" className="lb-fix-more" aria-expanded={more} onClick={() => setMore((m) => !m)} disabled={!!busy}>
            {more ? t('harvest.fewer') : t('fix.moreN', { n: rest })}
          </button>
        )}
        <button type="button" className="lb-fix-choice lb-fix-nothing" aria-pressed={empty} disabled={!!busy}
          onClick={() => choose('nothing')}>
          {empty && <CheckIcon size={16} weight="bold" aria-hidden="true" />}
          <span>{busy === 'nothing' ? t('common.saving') : t('fix.nothingFalse')}</span>
        </button>
        {err && <p className="lb-sheet-err" role="alert">{err}</p>}
      </div>
    </>
  )
}
