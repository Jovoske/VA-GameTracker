import { useEffect, useRef, useState } from 'react'
import { type Failure, type Got, HARVEST_DRAFT_KEY, api, getFresh, peek, peekMe, plainWords, whoAmI } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { type Key, cap, fmtDate, fmtTime, t } from '../i18n'
import { nightLabel, nightParts } from '../night'
import { newNoteId } from '../notes'
import { onSitSync } from '../sits'
import Overlay from './Overlay'
import { type Choice, loadChoices } from './PhotoFix'
import './harvest.css'

/**
 * The harvest book (feature 23): what was taken on the estate, for the season's
 * return. The morning after a SHOT, Tonight and Stands ask to log it (HarvestPrompt);
 * the one form (HarvestForm) takes species, sex, age, the seal number when there is
 * one, weight, when, and notes, and the same form changes a line later (Settings).
 *
 * No tallies and no leaderboards: the book is paperwork, not a score.
 */

/** A line of the book, as the server answers it (routes_harvests._out). */
export type HarvestLine = {
  id: string
  sit_id: string | null
  stand_id: string | null
  stand: string | null
  hunter: string
  yours: boolean
  species_id: string
  species: string
  sex: string
  age_class: string
  seal: string | null
  weight_kg: number | null
  notes: string | null
  taken_at: string
  created_at: string
  can_edit: boolean
}

/** A SHOT with nothing logged yet (GET /harvests/asks). */
export type HarvestAsk = { sit_id: string; stand_id: string; stand: string; night: string; shot_at: string | null }

export const SEXES: [string, Key][] = [['male', 'harvest.male'], ['female', 'harvest.female'], ['unknown', 'harvest.notSure']]
export const AGES: [string, Key][] = [
  ['juvenile', 'harvest.juvenile'], ['young_adult', 'harvest.youngAdult'], ['mature_adult', 'harvest.adult'],
  ['old', 'harvest.old'], ['unknown', 'harvest.notSure'],
]
const word = (list: [string, Key][], key: string) => {
  const k = list.find(([v]) => v === key)?.[1]
  return k ? t(k) : key
}

/** "Wild boar, male, adult · seal CU-0412": the line in a few words. */
export function lineWords(h: HarvestLine): string {
  const parts = [h.species]
  if (h.sex !== 'unknown') parts.push(word(SEXES, h.sex).toLocaleLowerCase())
  if (h.age_class !== 'unknown') parts.push(word(AGES, h.age_class).toLocaleLowerCase())
  return `${parts.join(', ')}${h.seal ? ` · ${t('harvest.seal', { seal: h.seal })}` : ''}`
}

const TIMEOUT_MS = 20_000

/** Why `what` (a key: "it wasn’t saved") went wrong, in a sentence. */
function failed(e: unknown, what: Key): string {
  const x = e as Failure
  if (x.offline) return t('harvest.failNoSignal', { what: t(what) })
  if (x.timeout) return t('harvest.failTimeout', { what: t(what) })
  return t('harvest.failOther', { reason: plainWords(x.message || t('common.wentWrong')), what: cap(t(what)) })
}

/** `2026-10-09T21:40` in this phone's clock, for a datetime-local field. */
function localInput(iso: string | number): string {
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

/** "Sat 26 Sep, 22:30": the form's time with its day in words beside the field, so a
 *  wrong day stands out (the field shows a bare date). Written as the phone writes
 *  dates, like the night headings (night.ts). */
function whenWords(local: string): string {
  const d = new Date(local)
  if (!local || Number.isNaN(d.getTime())) return ''
  const day = fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' })
  return `${day}, ${fmtTime(d)}`
}

/** "78.5" or "78,5" (a Spanish keyboard) as kg; null for nothing; NaN for nonsense. */
function kg(text: string): number | null {
  const t = text.trim().replace(',', '.')
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : NaN
}

type Draft = {
  /** A new line's id, made on the phone: saving again after no answer is the same line. */
  id: string
  species: string | null
  sex: string
  age: string
  seal: string
  weight: string
  when: string
  notes: string
  hunter: string
}

// What was typed, kept on the phone until it is saved: the form can close under a
// glove (Back, a call coming in) and open again with it all there. Signing out
// clears it (api.signOut).
const DRAFT_KEY = HARVEST_DRAFT_KEY
function readDraft(key: string): Draft | null {
  try {
    return JSON.parse(sessionStorage.getItem(DRAFT_KEY + key) || 'null')
  } catch {
    return null
  }
}
function keepDraft(key: string, d: Draft | null): void {
  try {
    if (d) sessionStorage.setItem(DRAFT_KEY + key, JSON.stringify(d))
    else sessionStorage.removeItem(DRAFT_KEY + key)
  } catch {
    // Private mode: the form still works, it just forgets on close.
  }
}

/**
 * The one form: log an animal (from a sit's SHOT, or by hand) or change a line.
 * Big buttons for the animal, sex and age; the seal number, weight, when and a note
 * are typed. An admin also writes who shot it (a guest, or the name the return wants).
 */
export function HarvestForm({ ask, line, stands, onClose, onSaved, onDeleted }: {
  /** The SHOT this is logged from, if any. */
  ask?: HarvestAsk | null
  /** The line being changed, if any. */
  line?: HarvestLine | null
  /** Where it was taken, for one logged by hand: the stands to pick from. */
  stands?: { id: string; name: string }[]
  onClose: () => void
  onSaved: (line: HarvestLine) => void
  onDeleted?: (id: string) => void
}) {
  const me = peekMe()
  const [admin, setAdmin] = useState(me?.role === 'admin')
  useEffect(() => { whoAmI().then((m) => setAdmin(m.role === 'admin')).catch(() => {}) }, [])
  const key = line ? `line-${line.id}` : ask ? `sit-${ask.sit_id}` : 'new'
  const [d, setD] = useState<Draft>(() => readDraft(key) ?? {
    id: line?.id ?? newNoteId(),
    species: line?.species_id ?? null,
    sex: line?.sex ?? 'unknown',
    age: line?.age_class ?? 'unknown',
    seal: line?.seal ?? '',
    weight: line?.weight_kg != null ? String(line.weight_kg) : '',
    when: localInput(line?.taken_at ?? ask?.shot_at ?? Date.now()),
    notes: line?.notes ?? '',
    hunter: line?.hunter ?? '',
  })
  const [stand, setStand] = useState<string>(line?.stand_id ?? '')
  const [choices, setChoices] = useState<Choice[] | null>(null)
  const [more, setMore] = useState(false)
  const [loadErr, setLoadErr] = useState('')
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null)
  const [err, setErr] = useState('')
  const [sure, setSure] = useState(false)
  // The overlay's own close, so leaving after a save takes its step off the history.
  const closeRef = useRef<() => void>(onClose)

  const set = (patch: Partial<Draft>) => setD((cur) => {
    const next = { ...cur, ...patch }
    keepDraft(key, next)
    return next
  })

  function loadList() {
    setLoadErr('')
    loadChoices().then(setChoices).catch((e) => setLoadErr(failed(e, 'harvest.what.list')))
  }
  useEffect(loadList, [])

  const likely = (choices ?? []).filter((c) => c.big_game || c.id === d.species)
  const rest = (choices ?? []).filter((c) => !likely.includes(c))

  async function save() {
    if (busy) return
    setErr('')
    if (!d.species) { setErr(t('harvest.pickFirst')); return }
    const weight = kg(d.weight)
    if (Number.isNaN(weight) || (weight != null && (weight <= 0 || weight >= 1000))) {
      setErr(t('harvest.weightKilos'))
      return
    }
    const at = d.when ? new Date(d.when) : null
    if (at && Number.isNaN(at.getTime())) { setErr(t('harvest.notADate')); return }
    if (at && at.getTime() > Date.now() + 10 * 60_000) { setErr(t('harvest.future')); return }
    const body: Record<string, unknown> = {
      species_id: d.species, sex: d.sex, age_class: d.age, seal: d.seal.trim() || null,
      weight_kg: weight, notes: d.notes.trim() || null, ...(at ? { taken_at: at.toISOString() } : {}),
      ...(admin && d.hunter.trim() ? { hunter: d.hunter.trim() } : {}),
      ...(!ask && !line?.sit_id ? { stand_id: stand || null } : {}),
    }
    setBusy('save')
    try {
      const saved = line
        ? await api<HarvestLine>(`/harvests/${line.id}`, { method: 'PATCH', body: JSON.stringify(body), timeoutMs: TIMEOUT_MS })
        : await api<HarvestLine>('/harvests', {
          method: 'POST', body: JSON.stringify({ ...body, id: d.id, ...(ask ? { sit_id: ask.sit_id } : {}) }), timeoutMs: TIMEOUT_MS,
        })
      keepDraft(key, null)
      onSaved(saved)
      closeRef.current()
    } catch (e) {
      setErr(failed(e, 'harvest.what.notSaved'))
    } finally {
      setBusy(null)
    }
  }

  async function remove() {
    if (!line || busy) return
    if (!sure) { setSure(true); return }
    setBusy('delete')
    setErr('')
    try {
      await api(`/harvests/${line.id}`, { method: 'DELETE', timeoutMs: TIMEOUT_MS })
      keepDraft(key, null)
      onDeleted?.(line.id)
      closeRef.current()
    } catch (e) {
      setErr(failed(e, 'harvest.what.notTakenOut'))
    } finally {
      setBusy(null)
    }
  }

  const where = ask ? `${ask.stand} · ${nightLabel(ask.night)}` : line?.stand ? line.stand : null
  const title = line ? t('harvest.changeTitle') : t('harvest.logTitle')

  return (
    <Overlay label={title} backLabel={t('common.back')} onClose={onClose} backdrop="var(--bg)" zIndex={60}
      style={{ flexDirection: 'column', alignItems: 'stretch', justifyContent: 'flex-start' }}>
      {(close) => { closeRef.current = close; return (
        <form className="hv-form" onSubmit={(e) => { e.preventDefault(); save() }} aria-busy={!!busy}>
          <h2>{title}</h2>
          {where && <p className="hv-where">{where}</p>}

          <fieldset className="hv-set">
            <legend>{t('harvest.whatWasIt')}</legend>
            {!choices && !loadErr && <p className="hv-dim" role="status">{t('harvest.loadingAnimals')}</p>}
            {loadErr && <p className="hv-err" role="alert">{loadErr} <button type="button" className="hv-link" onClick={loadList}>{t('common.tryAgain')}</button></p>}
            <div className="hv-grid">
              {[...likely, ...(more ? rest : [])].map((c) => (
                <button key={c.id} type="button" className="hv-choice" aria-pressed={d.species === c.id}
                  onClick={() => set({ species: c.id })}>{c.name}</button>
              ))}
            </div>
            {rest.length > 0 && (
              <button type="button" className="hv-link hv-more" aria-expanded={more} onClick={() => setMore((m) => !m)}>
                {more ? t('harvest.fewer') : t('harvest.more')}
              </button>
            )}
          </fieldset>

          <fieldset className="hv-set">
            <legend>{t('harvest.sex')}</legend>
            <div className="hv-row">
              {SEXES.map(([k, w]) => (
                <button key={k} type="button" className="hv-choice" aria-pressed={d.sex === k} onClick={() => set({ sex: k })}>{t(w)}</button>
              ))}
            </div>
          </fieldset>

          <fieldset className="hv-set">
            <legend>{t('harvest.age')}</legend>
            <div className="hv-grid">
              {AGES.map(([k, w]) => (
                <button key={k} type="button" className="hv-choice" aria-pressed={d.age === k} onClick={() => set({ age: k })}>{t(w)}</button>
              ))}
            </div>
          </fieldset>

          <div className="hv-pair">
            <label className="hv-field">
              <span>{t('harvest.sealNumber')} <small>{t('harvest.ifTagged')}</small></span>
              <input className="input" value={d.seal} maxLength={40} autoComplete="off" autoCapitalize="characters"
                onChange={(e) => set({ seal: e.target.value })} />
            </label>
            <label className="hv-field">
              <span>{t('harvest.weight')} <small>{t('harvest.ifWeighed')}</small></span>
              <input className="input" value={d.weight} inputMode="decimal" autoComplete="off"
                onChange={(e) => set({ weight: e.target.value })} />
            </label>
          </div>
          <label className="hv-field">
            <span>{t('harvest.when')} <small className="hv-when">{whenWords(d.when)}</small></span>
            <input className="input" type="datetime-local" value={d.when} max={localInput(Date.now())}
              onChange={(e) => set({ when: e.target.value })} />
          </label>
          {!ask && !line?.sit_id && stands && stands.length > 0 && (
            <label className="hv-field">
              <span>{t('harvest.where')}</span>
              <select className="input" value={stand} onChange={(e) => setStand(e.target.value)}>
                <option value="">{t('harvest.notAtStand')}</option>
                {stands.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
          )}
          {admin && (
            <label className="hv-field">
              <span>{t('harvest.whoShot')} <small>{line ? '' : t('harvest.whoShotHint')}</small></span>
              <input className="input" value={d.hunter} maxLength={60} autoComplete="off"
                onChange={(e) => set({ hunter: e.target.value })} />
            </label>
          )}
          <label className="hv-field">
            <span>{t('harvest.notes')}</span>
            <textarea className="input hv-notes" rows={3} value={d.notes} maxLength={500}
              onChange={(e) => set({ notes: e.target.value })} />
          </label>

          {err && <p className="hv-err" role="alert">{err}</p>}
          <button type="submit" className="btn hv-save" disabled={!!busy}>
            {busy === 'save' ? t('common.saving') : line ? t('harvest.saveChange') : t('harvest.logIt')}
          </button>
          {line && onDeleted && (
            <button type="button" className="hv-link hv-delete" onClick={remove} disabled={!!busy}>
              {busy === 'delete' ? t('harvest.takingOut') : sure ? t('harvest.tapAgain') : t('harvest.mistake')}
            </button>
          )}
        </form>
      ) }}
    </Overlay>
  )
}

type Done = { ask: HarvestAsk; words: string; line?: HarvestLine; nothing?: boolean }

/** "last night", "on Fri night", "on the night of Fri 18 Sep": when the SHOT was. */
function whenShot(night: string): string {
  const n = nightParts(night)
  if (n.kind === 'last') return t('harvest.shotLastNight')
  if (n.kind === 'tonight' || n.kind === 'today') return t('harvest.shotTonight')
  return n.kind === 'week' ? t('harvest.shotOnDay', { day: n.day }) : t('harvest.shotOnDate', { date: n.date })
}

/**
 * "You shot at Puente last night. Log it?" at the top of Tonight and Stands, the
 * morning after a SHOT, until it is logged or the hunter says there is nothing to log
 * (a miss, or an animal not found). One card per SHOT; it stays a moment with what
 * was saved, rather than vanishing under the thumb.
 */
export default function HarvestPrompt() {
  const [got, setGot] = useState<Got<HarvestAsk[]> | null>(() => peek<HarvestAsk[]>('/harvests/asks'))
  const [done, setDone] = useState<Record<string, Done>>({})
  const [open, setOpen] = useState<{ ask: HarvestAsk; line?: HarvestLine } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [errs, setErrs] = useState<Record<string, string>>({})
  const ctl = useRef<AbortController | null>(null)

  function load() {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    getFresh<HarvestAsk[]>('/harvests/asks', { signal: c.signal, save: true })
      .then((g) => { if (!c.signal.aborted) setGot(g) })
      .catch(() => {})
  }
  useEffect(() => {
    load()
    // A SHOT answered on "What happened last night?" (or sent once the signal came
    // back) asks straight away.
    const off = onSitSync((r) => { if (r.reports) load() })
    return () => {
      off()
      ctl.current?.abort()
    }
  }, [])
  useRefetchOnReturn(load)

  async function nothing(ask: HarvestAsk, yes: boolean) {
    if (busy) return
    setBusy(ask.sit_id)
    setErrs(({ [ask.sit_id]: _, ...rest }) => rest)
    try {
      await api(`/sits/${ask.sit_id}/no-harvest`, { method: 'POST', body: JSON.stringify({ nothing: yes }), timeoutMs: TIMEOUT_MS })
      setDone((cur) => {
        const { [ask.sit_id]: _, ...rest } = cur
        return yes ? { ...rest, [ask.sit_id]: { ask, words: t('harvest.nothingFrom', { stand: ask.stand }), nothing: true } } : rest
      })
    } catch (e) {
      setErrs((x) => ({ ...x, [ask.sit_id]: failed(e, 'harvest.what.notSaved') }))
    } finally {
      setBusy(null)
    }
  }

  // Only a list is a list: this card sits on top of Tonight and Stands, and an odd
  // answer (a proxy's page, an older server) must not take either page down with it.
  const asks = Array.isArray(got?.data) ? got.data : []
  const cards: Done[] = [
    ...Object.values(done),
    ...asks.filter((a) => !done[a.sit_id]).map((ask) => ({ ask, words: '' })),
  ]
  if (!cards.length && !open) return null

  return (
    <div className="hv-prompts">
      {cards.map(({ ask, words, line, nothing: none }) => (
        <section key={ask.sit_id} className="card hv-ask" aria-labelledby={`hv-ask-${ask.sit_id}`}>
          <h2 id={`hv-ask-${ask.sit_id}`}>{t('harvest.youShot', { stand: ask.stand, when: whenShot(ask.night) })}</h2>
          {words ? (
            <>
              <p className="hv-done" role="status">{words}</p>
              <div className="hv-after">
                {none ? (
                  <button type="button" className="hv-link" disabled={!!busy} onClick={() => nothing(ask, false)}>{t('common.undo')}</button>
                ) : (
                  <>
                    {line && <button type="button" className="hv-link" onClick={() => setOpen({ ask, line })}>{t('harvest.changeIt')}</button>}
                    <button type="button" className="hv-link" onClick={() => setOpen({ ask })}>{t('harvest.another')}</button>
                  </>
                )}
              </div>
            </>
          ) : (
            <>
              <p className="hv-dim">{t('harvest.askHint')}</p>
              <button type="button" className="hv-primary" disabled={!!busy} onClick={() => setOpen({ ask })}>{t('harvest.logAnimal')}</button>
              <button type="button" className="hv-link hv-nothing" disabled={!!busy} onClick={() => nothing(ask, true)}>
                {busy === ask.sit_id ? t('common.saving') : t('harvest.nothingToLog')}
              </button>
            </>
          )}
          {errs[ask.sit_id] && <p className="hv-err" role="alert">{errs[ask.sit_id]}</p>}
        </section>
      ))}
      {open && (
        <HarvestForm
          ask={open.line ? null : open.ask}
          line={open.line}
          onClose={() => setOpen(null)}
          onSaved={(saved) => {
            const ask = open.ask
            setDone((cur) => ({ ...cur, [ask.sit_id]: { ask, words: t('harvest.logged', { line: lineWords(saved) }), line: saved } }))
          }}
        />
      )}
    </div>
  )
}
