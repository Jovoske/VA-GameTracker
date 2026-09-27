import { useCallback, useEffect, useRef, useState } from 'react'
import { type Got, type StaleWhy, fromEarlierNight, getFresh, nightOf, noAnswer, noAnswerWords, peek } from '../api'
import { type Key, fmtTime, t, tOr } from '../i18n'
import { compass, windColor } from '../map/geometry'
import { hourGone, lineNow } from '../windline'
import './windweek.css'

/**
 * The wind hour by hour through the evening, tonight and the next six, for one stand
 * (backend forecasting/wind_week.py, feature 22).
 *
 * The line up front says when it is right: "Right wind for Charca: tonight 19–21 h,
 * Thu, Sat". The strip behind the fold is the week at a glance: a row an evening, a
 * column an hour from 17 to 24, each hour right (✓), wrong (✗) or too light to call
 * (~), with where the wind comes from under it, and an evening's speeds under it on
 * a tap. It is the same verdict Stands, the map and Sit mode give, judged for every
 * hour instead of one.
 */

export type WeekHour = {
  hour: number
  at: string
  at_local: string
  gone?: boolean
  status: string
  wind_dir_deg: number | null
  wind_speed_kmh: number | null
  source?: string | null
}
export type WeekStand = {
  stand_id: string
  stand: string
  status: string
  line: string
  right_tonight: string | null
  right_days: string[]
  evenings: { night: string; hours: WeekHour[]; right: string[]; right_evening: boolean }[]
  /** Tonight's verdict at the sit, as the map and Sit mode give it. */
  tonight?: { status: string; text: string; at_local?: string; now?: boolean }
}
export type WindWeek = {
  evenings: { night: string; day: string; tonight: boolean; sunset_local: string | null }[]
  hours: number[]
  stands: WeekStand[]
  forecast_fetched_at: string | null
  forecast_stale: boolean
  sunset_local?: string | null
}

const GLYPH: Record<string, string> = { clean: '✓', scent_carries: '✗', too_light: '~' }
/** A verdict on the wind (right, wrong, too light), not the reason there is none. */
export const judgedWind = (status: string | null | undefined) => !!status && status in GLYPH
/** An hour's verdict in words ("right wind"), for a screen reader. */
const word = (status: string) => tOr(`windWord.${status}`, status)
const estateClock = (iso: string) => fmtTime(iso, { timeZone: 'Europe/Madrid' })

/** What to do so a stand that can't be judged gets its hours. */
const UNJUDGED_NOTE: Record<string, Key> = {
  no_position: 'week.placeIt',
  no_bedding: 'week.drawBedding',
  no_geometry: 'week.setApproach',
}

/** The week's line says why there are no hours (a stand that can't be judged, no
 *  forecast at all), not when the wind is right. */
export const weekSaysWhy = (stand: WeekStand) =>
  stand.status !== 'ok' || stand.evenings.every((e) => e.hours.every((h) => h.status === 'no_wind_data'))

/** A copy made on an earlier night is last week's week: dropped, never shown as this one. */
const tonights = (got: Got<WindWeek> | null) => (got && !fromEarlierNight(got.at) ? got : null)

/**
 * The week's wind from `path` (/forecast/wind-week, all stands or ?stand=), painted
 * at once from what the phone kept and asked again. With no answer the copy the
 * phone has stays, with its age; with none, or only one from an earlier night,
 * `wait` says so in words. Once the asking is over it never says "Checking…": a
 * stand the answer doesn't hold reads "Wind not known yet" (review R6FE-1).
 */
export function useWindWeek(path: string | null) {
  const [got, setGot] = useState<Got<WindWeek> | null>(() => (path ? tonights(peek<WindWeek>(path)) : null))
  // Where the last ask is: under way, answered, or why nothing usable came back.
  const [asked, setAsked] = useState<'asking' | 'done' | StaleWhy | 'error'>('asking')
  const ctl = useRef<AbortController | null>(null)
  const reload = useCallback(() => {
    if (!path) return
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setAsked('asking')
    getFresh<WindWeek>(path, { signal: c.signal, save: true })
      .then((next) => {
        if (c.signal.aborted) return
        // The newest copy the phone has, and it is from an earlier night: nothing to show.
        const mine = tonights(next)
        setGot(mine)
        setAsked(mine ? 'done' : next.why ?? 'offline')
      })
      .catch((e) => { if (!c.signal.aborted) setAsked(noAnswer(e) ?? 'error') })
  }, [path])
  useEffect(() => {
    setGot(path ? tonights(peek<WindWeek>(path)) : null)
    reload()
    return () => ctl.current?.abort()
  }, [path, reload])
  const unknown = t('week.unknown')
  const wait = asked === 'asking' ? t('week.checking')
    : asked === 'error' ? `${t('week.couldnt')} ${unknown}`
      : asked !== 'done' ? `${noAnswerWords(asked)} ${unknown}`
        : got?.stale ? `${noAnswerWords(got.why)} ${unknown}` : unknown
  return { got, week: got?.data ?? null, wait, reload }
}

/** The one line: right hours tonight and the right evenings, or why it can't say.
 *  Tonight's hours are those not yet over by the phone's clock (windline.ts). */
export function WindWeekLine({ stand, className = '' }: { stand: WeekStand; className?: string }) {
  const now = Date.now()
  const said = lineNow(stand, nightOf(now), now)
  const right = said.right_tonight || said.right_days.length > 0
  return <p className={`ww-line ${className}`.trim()} data-right={right || undefined}>{said.line}</p>
}

/** The strip, for the fold. A tap on an evening puts its wind speeds under it, hour
 *  by hour: a phone has no hover to show them. */
export function WindWeekStrip({ week, stand }: { week: WindWeek; stand: WeekStand }) {
  const [open, setOpen] = useState<string | null>(null)
  const now = Date.now()
  // A stand that can't be judged has no hours to show: what to do instead, once.
  if (stand.status !== 'ok') return <p className="ww-note">{t(UNJUDGED_NOTE[stand.status] ?? 'week.cantJudge')}</p>
  const any = stand.evenings.some((e) => e.hours.some((h) => h.wind_dir_deg != null))
  if (!any) return <p className="ww-note">{t('week.noForecast')}</p>
  return (
    <div className="ww">
      <table className="ww-table">
        <caption className="sr-only">{t('week.caption', { stand: stand.stand })}</caption>
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">{t('week.evening')}</span></th>
            {week.hours.map((h) => <th key={h} scope="col">{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {stand.evenings.map((ev, i) => {
            const day = week.evenings[i]?.day ?? ev.night
            const shown = open === ev.night
            return [
              <tr key={ev.night} data-right={ev.right_evening ? 'true' : undefined} data-open={shown || undefined}
                onClick={() => setOpen(shown ? null : ev.night)}>
                <th scope="row">
                  {/* The speeds are in each hour's words already; the row is for the eye. */}
                  <button type="button" className="ww-day" aria-expanded={shown} aria-label={t('week.speedsOf', { day })}>{day}</button>
                </th>
                {ev.hours.map((h) => {
                  const from = h.wind_dir_deg != null ? compass(h.wind_dir_deg) : null
                  const said = from
                    ? t('week.hourFrom', { time: h.at_local, verdict: word(h.status), from, kmh: Math.round(h.wind_speed_kmh ?? 0) })
                    : t('week.hour', { time: h.at_local, verdict: word(h.status) })
                  return (
                    <td key={h.hour} data-status={h.status} data-gone={hourGone(h.at, now) || undefined}>
                      <span className="sr-only">{said}</span>
                      <span aria-hidden="true" className="ww-glyph" style={{ color: GLYPH[h.status] ? windColor(h.status) : undefined }}>
                        {GLYPH[h.status] ?? '·'}
                      </span>
                      <span aria-hidden="true" className="ww-from">{from ?? '–'}</span>
                    </td>
                  )
                })}
              </tr>,
              shown && (
                <tr key={`${ev.night}-speeds`} className="ww-speeds" aria-hidden="true">
                  <th scope="row">km/h</th>
                  {ev.hours.map((h) => (
                    <td key={h.hour} data-gone={hourGone(h.at, now) || undefined}>
                      {h.wind_speed_kmh != null ? Math.round(h.wind_speed_kmh) : '–'}
                    </td>
                  ))}
                </tr>
              ),
            ]
          })}
        </tbody>
      </table>
      <p className="ww-note">
        {t('week.key')}
        {week.evenings[0]?.sunset_local ? ` ${t('week.sunset', { day: week.evenings[0].tonight ? t('week.tonight') : week.evenings[0].day, time: week.evenings[0].sunset_local })}` : ''}
        {week.forecast_stale && week.forecast_fetched_at ? ` ${t('week.oldForecast', { time: estateClock(week.forecast_fetched_at) })}` : ''}
      </p>
    </div>
  )
}
