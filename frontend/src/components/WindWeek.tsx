import { useCallback, useEffect, useRef, useState } from 'react'
import { type Got, type StaleWhy, fromEarlierNight, getFresh, noAnswer, noAnswerWords, peek } from '../api'
import { compass, windColor } from '../map/geometry'
import './windweek.css'

/**
 * The wind hour by hour through the evening, tonight and the next six, for one stand
 * (backend forecasting/wind_week.py, feature 22).
 *
 * The line up front says when it is right: "Right wind for Charca: tonight 19–21 h,
 * Thu, Sat". The strip behind the fold is the week at a glance: a row an evening, a
 * column an hour from 17 to 24, each hour right (✓), wrong (✗) or too light to call
 * (~), with where the wind comes from under it. It is the same verdict Stands, the
 * map and Sit mode give, judged for every hour instead of one.
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
const WORD: Record<string, string> = {
  clean: 'right wind', scent_carries: 'wrong wind, scent blows to them', too_light: 'too light to call',
  no_wind_data: 'no forecast', no_bedding: 'no bedding drawn', no_position: 'not on the map', no_geometry: 'not judged',
}
const estateClock = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' })

/** An hour is gone once it is over; the hour under way still counts. Worked out on the
 *  phone, so a copy kept with no signal greys out what has passed since. */
const gone = (h: WeekHour, now: number) => Date.parse(h.at) + 3_600_000 <= now

/** A copy made on an earlier night is last week's week: dropped, never shown as this one. */
const tonights = (got: Got<WindWeek> | null) => (got && !fromEarlierNight(got.at) ? got : null)

/**
 * The week's wind from `path` (/forecast/wind-week, all stands or ?stand=), painted
 * at once from what the phone kept and asked again. With no answer the copy the
 * phone has stays, with its age; with none, `wait` says so in words, never a
 * spinner that doesn't end.
 */
export function useWindWeek(path: string | null) {
  const [got, setGot] = useState<Got<WindWeek> | null>(() => (path ? tonights(peek<WindWeek>(path)) : null))
  const [failed, setFailed] = useState<StaleWhy | 'error' | null>(null)
  const ctl = useRef<AbortController | null>(null)
  const reload = useCallback(() => {
    if (!path) return
    ctl.current?.abort()
    const c = new AbortController()
    ctl.current = c
    setFailed(null)
    getFresh<WindWeek>(path, { signal: c.signal, save: true })
      .then((next) => { if (!c.signal.aborted) setGot((had) => tonights(next) ?? had) })
      .catch((e) => { if (!c.signal.aborted) setFailed(noAnswer(e) ?? 'error') })
  }, [path])
  useEffect(() => {
    setGot(path ? tonights(peek<WindWeek>(path)) : null)
    reload()
    return () => ctl.current?.abort()
  }, [path, reload])
  const wait = failed
    ? `${failed === 'error' ? 'Couldn’t get the wind.' : noAnswerWords(failed)} Wind not known yet.`
    : 'Checking the wind…'
  return { got, week: got?.data ?? null, wait, reload }
}

/** The one line: right hours tonight and the right evenings, or why it can't say. */
export function WindWeekLine({ stand, className = '' }: { stand: WeekStand; className?: string }) {
  const right = stand.right_tonight || stand.right_days.length > 0
  return <p className={`ww-line ${className}`.trim()} data-right={right || undefined}>{stand.line}</p>
}

/** The strip, for the fold. */
export function WindWeekStrip({ week, stand }: { week: WindWeek; stand: WeekStand }) {
  const now = Date.now()
  const any = stand.evenings.some((e) => e.hours.some((h) => h.wind_dir_deg != null))
  if (!any) return <p className="ww-note">No hour-by-hour forecast for this week yet.</p>
  const judged = stand.status === 'ok'
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
            const meta = week.evenings[i]
            return (
              <tr key={ev.night} data-right={judged && ev.right_evening ? 'true' : undefined}>
                <th scope="row">{meta?.day ?? ev.night}</th>
                {ev.hours.map((h) => {
                  const from = h.wind_dir_deg != null ? compass(h.wind_dir_deg) : null
                  const said = `${h.at_local}: ${WORD[h.status] ?? h.status}${from ? `, from ${from} ${Math.round(h.wind_speed_kmh ?? 0)} km/h` : ''}`
                  return (
                    <td key={h.hour} data-status={h.status} data-gone={gone(h, now) || undefined} title={said}>
                      <span className="sr-only">{said}</span>
                      <span aria-hidden="true" className="ww-glyph" style={{ color: GLYPH[h.status] ? windColor(h.status) : undefined }}>
                        {GLYPH[h.status] ?? '·'}
                      </span>
                      <span aria-hidden="true" className="ww-from">{from ?? '–'}</span>
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="ww-note">
        {judged ? '✓ right: scent goes away from where they lie up. ✗ wrong: it blows to them. ~ too light to call. ' : ''}
        Letters: where the wind comes from.
        {week.evenings[0]?.sunset_local ? ` Sunset ${week.evenings[0].tonight ? 'tonight' : week.evenings[0].day} ${week.evenings[0].sunset_local}.` : ''}
        {week.forecast_stale && week.forecast_fetched_at ? ` No newer forecast: this one is from ${estateClock(week.forecast_fetched_at)}.` : ''}
      </p>
    </div>
  )
}
