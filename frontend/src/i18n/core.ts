import en from './en'

/**
 * The app's words in five languages, with nothing to install.
 *
 * Every word a hunter reads comes from one dictionary per language: English is in
 * the app itself, the others arrive only when somebody picks them (a few dozen KB
 * each, stored on the phone like the rest of the app for no signal). `t()` reads
 * the language in use at the moment it is called, so code outside React (an error
 * message, a night's heading) speaks it too; the page re-renders when it changes
 * (react.tsx).
 *
 * Nothing here touches the page at import time, so the node checks
 * (tests/night-rule.cjs, wind-line.cjs, i18n-keys.cjs) can load it.
 */
export type Lang = 'en' | 'fi' | 'sv' | 'nb' | 'es'
export type Key = keyof typeof en
/** A word that changes with a count: "1 photo", "2 photos". Intl.PluralRules picks the form. */
export type Forms = { zero?: string; one?: string; two?: string; few?: string; many?: string; other: string }
export type Entry = string | Forms
export type Dict = { [K in Key]: (typeof en)[K] extends string ? string : Forms }
export type Params = Record<string, string | number | null | undefined>

/** Each language named in itself, as the picker shows it, with the Intl locale that
 *  writes its dates, times and numbers (a 24-hour clock in all five). */
export const LANGS: { code: Lang; name: string; locale: string }[] = [
  { code: 'en', name: 'English', locale: 'en-GB' },
  { code: 'fi', name: 'Suomi', locale: 'fi-FI' },
  { code: 'sv', name: 'Svenska', locale: 'sv-SE' },
  { code: 'nb', name: 'Norsk (bokmål)', locale: 'nb-NO' },
  { code: 'es', name: 'Español', locale: 'es-ES' },
]

/** Where the phone keeps the language, through sign-out: it belongs to the phone too. */
export const LANG_KEY = 'gs_lang'

export const isLang = (x: unknown): x is Lang => LANGS.some((l) => l.code === x)

const loaders: Record<Exclude<Lang, 'en'>, () => Promise<{ default: Dict }>> = {
  fi: () => import('./fi'),
  sv: () => import('./sv'),
  nb: () => import('./nb'),
  es: () => import('./es'),
}

const dicts: Partial<Record<Lang, Dict>> = { en: en as Dict }
let current: Lang = 'en'
let wanted: Lang = 'en'
const listeners = new Set<() => void>()

/** The language on screen now. */
export function lang(): Lang {
  return current
}

/** Its Intl locale: "fi-FI". */
export function locale(): string {
  return LANGS.find((l) => l.code === current)!.locale
}

export function subscribe(f: () => void): () => void {
  listeners.add(f)
  return () => { listeners.delete(f) }
}

function stored(): Lang | null {
  try {
    const v = typeof localStorage === 'undefined' ? null : localStorage.getItem(LANG_KEY)
    return isLang(v) ? v : null
  } catch {
    return null
  }
}

function store(code: Lang): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(LANG_KEY, code)
  } catch {
    // Private mode: the language holds for this visit.
  }
}

async function load(code: Lang): Promise<Dict> {
  const have = dicts[code]
  if (have) return have
  const dict = (await loaders[code as Exclude<Lang, 'en'>]()).default
  dicts[code] = dict
  return dict
}

function apply(code: Lang): void {
  if (current === code) return
  current = code
  plurals = null
  if (typeof document !== 'undefined') document.documentElement.lang = code
  listeners.forEach((f) => f())
}

/**
 * Speak `code` from now on, and remember it on this phone. Resolves once its words
 * are here and on screen; until then the language before stays, so nothing flashes.
 * A language that won't load (no signal on a first visit) leaves the one before.
 */
export async function setLanguage(code: Lang): Promise<void> {
  if (!isLang(code)) return
  wanted = code
  store(code)
  await load(code)
  // A later choice made while this one loaded wins.
  if (wanted === code) apply(code)
}

/** The phone's saved language, loaded before the first paint (main.tsx), for at most
 *  `waitMs`: a phone that can't fetch it opens in English and switches when it can. */
export function startLanguage(waitMs = 2500): Promise<void> {
  const code = stored()
  if (!code || code === 'en') {
    if (typeof document !== 'undefined') document.documentElement.lang = 'en'
    return Promise.resolve()
  }
  const going = setLanguage(code).catch(() => {})
  return Promise.race([going, new Promise<void>((r) => setTimeout(r, waitMs))])
}

let plurals: Intl.PluralRules | null = null
function form(entry: Forms, count: number): string {
  plurals ??= new Intl.PluralRules(locale())
  return entry[plurals.select(count) as keyof Forms] ?? entry.other
}

/** `{name}` in `text`, from `params`. A missing one stays visible, so it gets noticed. */
export function fill(text: string, params?: Params): string {
  if (!params) return text
  return text.replace(/\{(\w+)\}/g, (m, name: string) => {
    const v = params[name]
    return v == null ? m : String(v)
  })
}

function entryOf(key: Key): Entry {
  return (dicts[current]?.[key] as Entry | undefined) ?? (en[key] as Entry | undefined) ?? key
}

/** The words for `key` in the language on screen, `{name}`s filled from `params`. An
 *  entry with forms picks one by `params.count`. */
export function t(key: Key, params?: Params): string {
  const entry = entryOf(key)
  const text = typeof entry === 'string' ? entry : form(entry, Number(params?.count ?? 0))
  return fill(text, params)
}

/** Whether `key` has words: for keys made from data (a status the server sent). */
export function has(key: string): key is Key {
  return key in en
}

/** `key`'s words when there are any, else `fallback`: a status from the server this
 *  app doesn't know yet is shown as the server says it. */
export function tOr(key: string, fallback: string, params?: Params): string {
  return has(key) ? t(key, params) : fallback
}
