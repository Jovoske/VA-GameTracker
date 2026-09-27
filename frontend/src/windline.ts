/**
 * A stand's wind line for the week, as it stands now (feature 22).
 *
 * The server writes the line when it answers (backend forecasting/wind_week.py:
 * `_runs`, `_named`, `_line`): "Right wind for Charca: tonight 19–21 h, Thu, Sat",
 * tonight's right hours still to come. A copy kept on the phone and read hours later
 * with no signal would still offer "tonight 19–21 h" at 22:30, under "Plan from just
 * now" (review R6FE-4). The copy holds every hour, so once an hour the server counted
 * as still to come is over, tonight's part is made again here from the hours left,
 * by the same rule. Otherwise the server's line stands.
 *
 * On its own, with nothing from the browser, so tests/wind-line.cjs can check it
 * against the server's cases.
 */

type Hour = { hour: number; at: string; gone?: boolean; status: string }
type Stand = {
  stand: string
  status: string
  line: string
  right_tonight: string | null
  right_days: string[]
  evenings: { night: string; hours: Hour[] }[]
}
export type LineNow = { line: string; right_tonight: string | null; right_days: string[] }

// As the server keeps them (wind_week.RIGHT, MIN_RUN, NAMED).
const RIGHT = 'clean'
const MIN_RUN = 2
const NAMED = 2

/** An hour is over once its 60 minutes are; the hour under way still counts. */
export const hourGone = (at: string, now: number) => Date.parse(at) + 3_600_000 <= now

/** "19–21 h", or "21 h" for one hour. */
const span = (run: number[]) => (run.length === 1 ? `${run[0]} h` : `${run[0]}–${run[run.length - 1]} h`)

/** The right hours in a row, among those still to come. */
function runs(hours: Hour[], now: number): number[][] {
  const out: number[][] = []
  let last: number | null = null
  for (const h of hours) {
    if (h.gone || hourGone(h.at, now) || h.status !== RIGHT) {
      last = null
      continue
    }
    if (last !== null && h.hour === last + 1 && out.length) out[out.length - 1].push(h.hour)
    else out.push([h.hour])
    last = h.hour
  }
  return out
}

/** The runs the line names: a sit's worth or more first, the longest of them, then
 *  single hours if there is room; in time order. */
function named(all: number[][]): number[][] {
  const ranked = [...all].sort((a, b) =>
    Number(a.length < MIN_RUN) - Number(b.length < MIN_RUN) || b.length - a.length || a[0] - b[0])
  return ranked.slice(0, NAMED).sort((a, b) => a[0] - b[0])
}

/**
 * The stand's line at `now`, `tonight` being tonight's night ("2026-09-24", as
 * night.ts nightOf gives it). The server's own while every hour it counted as still
 * to come is; else with tonight's part made again from the hours left. A stand that
 * can't be judged, or a week with no forecast, says so whatever the hour.
 */
export function lineNow(stand: Stand, tonight: string, now: number): LineNow {
  const same = { line: stand.line, right_tonight: stand.right_tonight, right_days: stand.right_days }
  const ev = stand.evenings.find((e) => e.night === tonight)
  if (stand.status !== 'ok' || !ev || !ev.hours.some((h) => !h.gone && hourGone(h.at, now))) return same
  if (stand.evenings.every((e) => e.hours.every((h) => h.status === 'no_wind_data'))) return same
  const said = named(runs(ev.hours, now)).map(span).join(' and ') || null
  const right = [...(said ? [`tonight ${said}`] : []), ...stand.right_days]
  return {
    line: right.length ? `Right wind for ${stand.stand}: ${right.join(', ')}` : `No right wind for ${stand.stand} this week.`,
    right_tonight: said,
    right_days: stand.right_days,
  }
}
