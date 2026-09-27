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

const wallClock = new Intl.DateTimeFormat('en-GB', {
  timeZone: ESTATE_TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  second: '2-digit', hourCycle: 'h23',
})
const parts = (when: string | number | Date, clock = estateClock) =>
  Object.fromEntries(clock.formatToParts(new Date(when)).map((x) => [x.type, x.value]))

/** The estate's calendar day of `when`, with the hours before `hour` o'clock still
 *  counted as the day before. On the wall clock, not the UTC one, as the server does. */
function dayFrom(when: string | number | Date, hour: number): string {
  const p = parts(when)
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) - hour * 3600e3
  return new Date(wall).toISOString().slice(0, 10)
}

/** The hour on the estate's clock, 0 to 23. */
function estateHour(when: string | number | Date): number {
  return +parts(when).hour
}

/** `2026-09-25_22-05-07`: the moment on the estate's clock, for a saved photo's name,
 *  as the server names its downloads (routes_images.download_name). */
export function estateStamp(when: string | number | Date): string {
  const p = parts(when, wallClock)
  return `${p.year}-${p.month}-${p.day}_${p.hour}-${p.minute}-${p.second}`
}

/** A night's date ("2026-09-24") as the phone writes dates, with `opts`. */
function nightDate(night: string, opts: Intl.DateTimeFormatOptions): string {
  return new Date(`${night}T12:00:00Z`).toLocaleDateString(undefined, { ...opts, timeZone: 'UTC' })
}

/**
 * The heading over a night's photos: "Tonight" (or "Today" before 18:00), "Last night",
 * "Thu night" this past week, then "Night of Thu 18 Sep". A night is the server's:
 * 06:00 to 06:00 on the estate's clock, so last night's photos after midnight are
 * under "Last night" with the rest of it, not under "Today" (audit I-27).
 */
export function nightLabel(night: string, now: number = Date.now()): string {
  const tonight = nightOf(now)
  if (night === tonight) {
    const h = estateHour(now)
    return h >= 18 || h < 6 ? 'Tonight' : 'Today'
  }
  if (night === nightBefore(tonight)) return 'Last night'
  if (night > nightBefore(tonight, 7)) return `${nightDate(night, { weekday: 'short' })} night`
  return `Night of ${nightDate(night, { weekday: 'short', day: 'numeric', month: 'short' })}`
}

/** 18:00 to 06:00 on the estate's clock: the dark part of a night. */
function dark(when: string | number | Date): boolean {
  const h = estateHour(when)
  return h >= 18 || h < 6
}

/**
 * The heading over a run of photos, by what the run holds, in the words whenSeen
 * uses for the same photos. A night's dark hours (18:00 to 06:00) are "Tonight",
 * "Last night", "Thu night", "Night of Thu 18 Sep"; its daytime (06:00 to 18:00) is
 * "Today", "Yesterday", "Thursday", "Thu 18 Sep". At 19:30 this morning's deer used to
 * be under "Tonight", and yesterday's under "Last night": a night runs 06:00 to 06:00.
 * `key` groups the photos: one heading for each part of each night.
 */
export function photoHeading(iso: string, now: number = Date.now()): { key: string; label: string } {
  const night = nightOf(iso)
  if (dark(iso)) return { key: `${night}:night`, label: night === nightOf(now) ? 'Tonight' : nightLabel(night, now) }
  const tonight = nightOf(now)
  const label = night === tonight ? 'Today'
    : night === nightBefore(tonight) ? 'Yesterday'
      : night > nightBefore(tonight, 7) ? nightDate(night, { weekday: 'long' })
        : nightDate(night, { weekday: 'short', day: 'numeric', month: 'short' })
  return { key: `${night}:day`, label }
}

/**
 * When something was last on camera, as a hunter says it: "tonight", "today", "last
 * night", "yesterday", "Tuesday night", "Tuesday", or "3 Sep" before that. It used to
 * count 24-hour spans, so at 08:00 a boar from 21:30 last night was "seen today"
 * while Photos filed it under yesterday (audit C-14).
 */
export function whenSeen(iso: string, now: number = Date.now()): string {
  const night = nightOf(iso)
  const tonight = nightOf(now)
  const inDark = dark(iso)
  if (night === tonight) return inDark ? 'tonight' : 'today'
  if (night === nightBefore(tonight)) return inDark ? 'last night' : 'yesterday'
  if (night > nightBefore(tonight, 7)) return `${nightDate(night, { weekday: 'long' })}${inDark ? ' night' : ''}`
  return nightDate(night, { day: 'numeric', month: 'short' })
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
