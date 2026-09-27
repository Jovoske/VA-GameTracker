import { Fragment, type ReactNode, useSyncExternalStore } from 'react'
import { type Key, type Lang, type Params, lang, subscribe, t } from './core'

/**
 * The language on screen, for React. The app's root reads it (App.tsx), so a new
 * language re-renders every page from the top at once, with nothing lost: no page
 * is mounted again, a half-typed form stays typed.
 */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, lang, lang)
}

/** `t` for a component that wants to say it follows the language itself. */
export function useT(): typeof t {
  useLang()
  return t
}

/**
 * Words with something inside them that isn't text: a link, a bold name, a button.
 * The dictionary keeps the sentence whole ("Turn them on in {link}."), so each
 * language puts the link where its own sentence needs it.
 */
export function tn(key: Key, parts: Record<string, ReactNode>, params?: Params): ReactNode {
  const text = t(key, params)
  const out: ReactNode[] = []
  let at = 0
  let i = 0
  for (const m of text.matchAll(/\{(\w+)\}/g)) {
    if (!(m[1] in parts)) continue
    if (m.index! > at) out.push(text.slice(at, m.index))
    out.push(<Fragment key={i++}>{parts[m[1]]}</Fragment>)
    at = m.index! + m[0].length
  }
  if (at < text.length) out.push(text.slice(at))
  return <>{out}</>
}
