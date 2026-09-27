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

export function nightOf(when: string | number | Date): string {
  const p = Object.fromEntries(estateClock.formatToParts(new Date(when)).map((x) => [x.type, x.value]))
  // Six hours back on the wall clock (not the UTC one), as the server does.
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute) - 6 * 3600e3
  return new Date(wall).toISOString().slice(0, 10)
}

/** Made before this morning's 06:00: it belongs to an earlier night than tonight. */
export function fromEarlierNight(iso: string, now: number = Date.now()): boolean {
  return nightOf(iso) < nightOf(now)
}
