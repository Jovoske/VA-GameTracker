import { locale, t } from './core'

/**
 * Dates, times, weekdays and numbers in the language on screen, through Intl with
 * its locale (en-GB, fi-FI, sv-SE, nb-NO, es-ES). Always a 24-hour clock: a hunter
 * reads "21:40", never "9:40 PM", whatever the phone's own region says. The phone's
 * time zone unless `timeZone` says otherwise (the estate's clock, Europe/Madrid).
 */
const formats = new Map<string, Intl.DateTimeFormat>()

function dateFormat(opts: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const loc = locale()
  const withClock = opts.hour || opts.minute || opts.timeStyle ? { hourCycle: 'h23' as const, ...opts } : opts
  const key = `${loc}|${JSON.stringify(withClock)}`
  let f = formats.get(key)
  if (!f) formats.set(key, (f = new Intl.DateTimeFormat(loc, withClock)))
  return f
}

type When = string | number | Date

/** Any part of a date, as `opts` asks: fmtDate(d, { day: 'numeric', month: 'short' }) is "4 Sept". */
export function fmtDate(when: When, opts: Intl.DateTimeFormatOptions): string {
  return dateFormat(opts).format(new Date(when))
}

/** "21:40" (in Finnish "21.40"). */
export function fmtTime(when: When, opts: Intl.DateTimeFormatOptions = {}): string {
  return fmtDate(when, { hour: '2-digit', minute: '2-digit', ...opts })
}

/** "Thu" or "Thursday". */
export function fmtWeekday(when: When, style: 'short' | 'long' = 'short', opts: Intl.DateTimeFormatOptions = {}): string {
  return fmtDate(when, { weekday: style, ...opts })
}

const numbers = new Map<string, Intl.NumberFormat>()

/** 12,345 / 12 345 / 12.345, as the language writes it. */
export function fmtNumber(n: number, opts: Intl.NumberFormatOptions = {}): string {
  const loc = locale()
  const key = `${loc}|${JSON.stringify(opts)}`
  let f = numbers.get(key)
  if (!f) numbers.set(key, (f = new Intl.NumberFormat(loc, opts)))
  return f.format(n)
}

/** How long ago, in whole minutes, from `iso` to now. */
export const minutesSince = (iso: string, now = Date.now()) => Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000))

/** "just now", "5 min ago", "3 h ago", "2 d ago": short, the way the app has always
 *  said it, with the number written in the language's own way. */
export function ago(iso: string, now = Date.now()): string {
  const mins = minutesSince(iso, now)
  if (mins < 2) return t('time.justNow')
  if (mins < 60) return t('time.minAgo', { n: fmtNumber(mins) })
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return t('time.hAgo', { n: fmtNumber(hrs) })
  const days = Math.round(hrs / 24)
  return t('time.dAgo', { n: fmtNumber(days) })
}

/** "3 h", "2 d": how long something has lasted since `iso` (a login failing). */
export function lasted(iso: string, now = Date.now()): string {
  const mins = minutesSince(iso, now)
  if (mins < 2) return t('time.justNow')
  if (mins < 60) return t('time.min', { n: fmtNumber(mins) })
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return t('time.h', { n: fmtNumber(hrs) })
  const days = Math.round(hrs / 24)
  return t('time.d', { n: fmtNumber(days) })
}

/** "Charca, Puente and Olivo": a list in words, the language's "and" before the last. */
export function fmtList(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return t('common.andList', { list: items.slice(0, -1).join(', '), last: items[items.length - 1] })
}

/** A heading's first letter up: Finnish, Swedish, Norwegian and Spanish write their
 *  weekdays and months small ("torstai"), which is right mid-sentence, not on top. */
export function cap(text: string): string {
  return text ? text[0].toLocaleUpperCase(locale()) + text.slice(1) : text
}
