/**
 * The night a moment belongs to, as the server counts them: the estate's own clock,
 * with anything before 06:00 still part of the evening before. "2026-10-03" is the
 * night of 3 to 4 October. A plan or a reservation from another night is not
 * tonight's, however recent it looks.
 *
 * On its own, with nothing from the browser, so tests/night-rule.cjs can check it
 * across the clock changes.
 */
const ESTATE_TZ = 'Europe/Madrid'
const estateClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: ESTATE_TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

/** The estate's calendar day of `when`, with the hours before `hour` o'clock still
 *  counted as the day before. On the wall clock, not the UTC one, as the server does. */
function dayFrom(when: string | number | Date, hour: number): string {
  const p = Object.fromEntries(estateClock.formatToParts(new Date(when)).map((x) => [x.type, x.value]))
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) - hour * 3600e3
  return new Date(wall).toISOString().slice(0, 10)
}

export function nightOf(when: string | number | Date): string {
  return dayFrom(when, 6)
}

/** The night `days` before `night` ("2026-09-27" → "2026-09-26"), by the calendar. */
export function nightBefore(night: string, days = 1): string {
  return new Date(Date.parse(`${night}T00:00:00Z`) - days * 86_400_000).toISOString().slice(0, 10)
}

// As the server keeps them (routes_stands LIVE_FOR, DAWN_FROM, DAWN_FOR).
const LIVE_FOR_MS = 12 * 3600e3
const DAWN_FROM_HOUR = 3
const DAWN_FOR_MS = 6 * 3600e3

/** Started from 03:00 on the morning `night` began: a dawn start. */
export function dawnStart(startedAt: string, night: string): boolean {
  return dayFrom(startedAt, DAWN_FROM_HOUR) >= night
}

/**
 * Whether a sit of `night`, started at `startedAt` and not ended, is still on.
 * While its night lasts, for up to 12 hours. After the 06:00 changeover only a
 * dawn sit is (reserved before 06:00, started from 03:00), for up to 6 hours: an
 * evening sit nobody ended is over, because the hunter walked home.
 */
export function startedSitIsOn(night: string, startedAt: string, now: number = Date.now()): boolean {
  const tonight = nightOf(now)
  const age = now - Date.parse(startedAt)
  if (night === tonight) return age < LIVE_FOR_MS
  return night === nightBefore(tonight) && dawnStart(startedAt, tonight) && age < DAWN_FOR_MS
}

/** Made before this morning's 06:00: it belongs to an earlier night than tonight. */
export function fromEarlierNight(iso: string, now: number = Date.now()): boolean {
  return nightOf(iso) < nightOf(now)
}
