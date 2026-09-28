import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { type Got, getFresh, nightBefore, nightOf, peek } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { type Key, fmtTime, fmtWeekday, t } from '../i18n'
import { dawnStart } from '../night'
import { isOn, onSitSync, saveSit, withPending } from '../sits'
import './sitprompts.css'

/**
 * What your sits still want from you, at the top of Tonight and Stands.
 *
 * - "Back to sit" while one is on (Tonight only; Stands has it on the stand). The
 *   phone kills an installed app mid-sit and it reopens on Tonight, which used to
 *   have no way back in (audit J-03).
 * - "What happened last night?" for a sit nobody reported, one tap to answer. The
 *   report used to be possible only until 06:00, so quiet sits stayed "unreported"
 *   for good and the record leant towards the good nights (J-22). Stands asks only
 *   about earlier nights: tonight's ended sit asks on its own stand.
 *
 * Which is which is decided here, by the same rule as the server (sits.ts isOn), not
 * by the list a sit came in: a copy saved at 05:50 must not keep an evening sit
 * nobody ended "on" at 07:30. At 06:00 it becomes a question.
 */

type MySit = {
  id: string
  stand_id: string
  stand: string | null
  night: string
  outcome: string
  started_at: string | null
  ended_at: string | null
}
type Mine = { live: MySit[]; to_report: MySit[] }

const ANSWERS: [string, Key][] = [
  ['nothing', 'outcome.nothing'],
  ['seen', 'outcome.seen'],
  ['shootable_no_shot', 'outcome.shootable_no_shot'],
  ['shot', 'outcome.shot'],
]
/** What was answered, as the card says it after "Saved:". */
const said = (outcome: string) => t(outcome === 'cancelled' ? 'sitAsk.youDidntGo' : (`outcome.said.${outcome}` as Key))

// As the server asks (routes_stands.ASK_NIGHTS): older than this, the moment has gone.
const ASK_NIGHTS = 3

function whenWords(sit: MySit, tonight: string): string {
  if (sit.night === tonight) return t('sitAsk.thisEvening')
  // A dawn sit reserved before 06:00 belongs to the night before, but it was this morning.
  if (sit.night === nightBefore(tonight)) return sit.started_at && dawnStart(sit.started_at, tonight) ? t('sitAsk.thisMorning') : t('sitAsk.lastNight')
  const day = fmtWeekday(`${sit.night}T12:00:00Z`, 'long', { timeZone: 'UTC' })
  return t('sitAsk.onDayNight', { day })
}

const clock = (iso: string) => fmtTime(iso)

export default function SitPrompts({ page }: { page: 'tonight' | 'stands' }) {
  const [got, setGot] = useState<Got<Mine> | null>(() => peek<Mine>('/sits/mine'))
  // Answered here: the card stays with what was saved, rather than vanishing under
  // the thumb before the hunter has seen it took.
  const [answered, setAnswered] = useState<Record<string, { sit: MySit; words: string }>>({})
  const [errs, setErrs] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [, setSynced] = useState(0)
  const ctl = useRef<AbortController | null>(null)

  function load() {
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    getFresh<Mine>('/sits/mine', { signal: c.signal, save: true })
      .then((g) => { if (!c.signal.aborted) setGot(g) })
      .catch(() => {})
  }
  useEffect(() => {
    load()
    // A report that was waiting for signal went: the card can say so, and the list
    // is asked for again.
    const off = onSitSync((r) => {
      setSynced((n) => n + 1)
      if (r.sent) load()
    })
    return () => {
      off()
      ctl.current?.abort()
    }
  }, [])
  useRefetchOnReturn(load)

  async function answer(sit: MySit, outcome: string) {
    if (busy) return
    setBusy(sit.id)
    setErrs(({ [sit.id]: _, ...rest }) => rest)
    try {
      // A plain report, not a correction: it can only fill in an unreported sit, so
      // a card painted from an old copy can't lower a report made since. "Didn't go"
      // cancels the reservation, which the server allows only while unreported.
      const how = await saveSit(sit.id, outcome === 'cancelled' ? { outcome, correct: true } : { outcome })
      const what = said(outcome)
      const words = how === 'queued' ? t('sitAsk.savedPhone', { what }) : t('sitAsk.saved', { what })
      setAnswered((a) => ({ ...a, [sit.id]: { sit, words } }))
    } catch (e) {
      setErrs((x) => ({ ...x, [sit.id]: t('common.notSaved', { why: (e as Error).message }) }))
    } finally {
      setBusy(null)
    }
  }

  const tonight = nightOf(Date.now())
  const oldest = nightBefore(tonight, ASK_NIGHTS)
  const all = [...new Map([...(got?.data.live ?? []), ...(got?.data.to_report ?? [])].map((s) => [s.id, s])).values()].map(withPending)
  const live = page === 'tonight' ? all.filter((s) => isOn(s)) : []
  const ask = all
    .filter((s) => !isOn(s) && !answered[s.id] && s.outcome === 'unreported' && s.night >= oldest)
    .filter((s) => (page === 'stands' ? s.night < tonight : s.night < tonight || !!s.ended_at || !!s.started_at))
  const cards = [...Object.values(answered).map((a) => ({ sit: a.sit, words: a.words })), ...ask.map((sit) => ({ sit, words: '' }))]
  if (!live.length && !cards.length) return null

  return (
    <div className="sp">
      {live.map((s) => (
        <section key={s.id} className="card sp-live" aria-label={t('sitAsk.onLabel')}>
          <p>
            <strong>{t('sitAsk.on', { stand: s.stand ?? t('sitAsk.yourStandLower') })}</strong>
            {s.started_at && <> {t('sitAsk.since', { time: clock(s.started_at) })}</>}
          </p>
          <Link className="sp-primary" to={`/sit/${s.id}`}>{t('sitAsk.back')}</Link>
        </section>
      ))}
      {cards.map(({ sit, words }) => (
        <section key={sit.id} className="card sp-ask" aria-labelledby={`sp-ask-${sit.id}`}>
          <h2 id={`sp-ask-${sit.id}`}>{t('sitAsk.whatHappened', { when: whenWords(sit, tonight) })}</h2>
          <p className="sp-where">
            {sit.stand ?? t('sitAsk.yourStand')}.{' '}
            {words ? '' : sit.ended_at ? t('sitAsk.endedSilent') : sit.started_at ? t('sitAsk.startedSilent') : t('sitAsk.reservedSilent')}
          </p>
          {words ? (
            <p className="sp-done" role="status">{words}</p>
          ) : (
            <>
              <div className="sp-answers" role="group" aria-label={t('sitAsk.whatHappenedAt', { stand: sit.stand ?? t('sitAsk.yourStandLower') })}>
                {ANSWERS.map(([value, text]) => (
                  <button key={value} className="sp-answer" disabled={!!busy} onClick={() => answer(sit, value)}>
                    {t(text)}
                  </button>
                ))}
              </div>
              {!sit.started_at && (
                <button className="sp-didnt" disabled={!!busy} onClick={() => answer(sit, 'cancelled')}>
                  {t('sitAsk.iDidntGo')}
                </button>
              )}
            </>
          )}
          {errs[sit.id] && <p className="sp-err" role="alert">{errs[sit.id]}</p>}
        </section>
      ))}
    </div>
  )
}
