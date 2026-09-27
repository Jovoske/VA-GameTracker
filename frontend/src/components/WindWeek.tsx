import { useCallback, useEffect, useRef, useState } from 'react'
import { type Got, type StaleWhy, fromEarlierNight, getFresh, nightOf, noAnswer, noAnswerWords, peek } from '../api'
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
const WORD: Record<string, string> = {
  clean: 'right wind', scent_carries: 'wrong wind, scent blows to them', too_light: 'too light to call',
  no_wind_data: 'no forecast', no_bedding: 'no bedding drawn', no_position: 'not on the map', no_geometry: 'not judged',
}
const estateClock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' })

/** What to do so a stand that can't be judged gets its hours. */
const UNJUDGED_NOTE: Record<string, string> = {
  no_position: 'Place it on the map to see its wind hour by hour.',
  no_bedding: 'Draw where they lie up on the map to see its wind hour by hour.',
  no_geometry: 'Set its approach directions on the map to see its wind hour by hour.',
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
  const unknown = 'Wind not known yet.'
  const wait = asked === 'asking' ? 'Checking the wind…'
    : asked === 'error' ? `Couldn’t get the wind. ${unknown}`
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
  if (stand.status !== 'ok') return <p className="ww-note">{UNJUDGED_NOTE[stand.status] ?? 'Its wind can’t be judged hour by hour yet.'}</p>
  const any = stand.evenings.some((e) => e.hours.some((h) => h.wind_dir_deg != null))
  if (!any) return <p className="ww-note">No hour-by-hour forecast for this week yet.</p>
  return (
    <div className="ww">
      <table className="ww-table">
        <caption className="sr-only">Wind at {stand.stand}, hour by hour, tonight and the next six evenings</caption>
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">Evening</span></th>
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
                  <button type="button" className="ww-day" aria-expanded={shown} aria-label={`${day}: wind speeds`}>{day}</button>
                </th>
                {ev.hours.map((h) => {
                  const from = h.wind_dir_deg != null ? compass(h.wind_dir_deg) : null
                  const said = `${h.at_local}: ${WORD[h.status] ?? h.status}${from ? `, from ${from} ${Math.round(h.wind_speed_kmh ?? 0)} km/h` : ''}`
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
        ✓ right: scent goes away from where they lie up. ✗ wrong: it blows to them. ~ too light to call.
        Letters: where the wind comes from. Tap an evening for its wind speeds.
        {week.evenings[0]?.sunset_local ? ` Sunset ${week.evenings[0].tonight ? 'tonight' : week.evenings[0].day} ${week.evenings[0].sunset_local}.` : ''}
        {week.forecast_stale && week.forecast_fetched_at ? ` No newer forecast: this one is from ${estateClock(week.forecast_fetched_at)}.` : ''}
      </p>
    </div>
  )
}
