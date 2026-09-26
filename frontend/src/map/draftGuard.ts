/**
 * An outline that isn't saved yet, so leaving the map can ask first.
 *
 * react-router's useBlocker needs a data router and this app uses BrowserRouter, so
 * the tab links check this flag themselves, and the browser gets a beforeunload for
 * reloads and closing the tab (B-12).
 */
let unsaved = ''

export function setUnsavedDraft(what: string) { unsaved = what }

/** True when it is fine to leave: nothing unsaved, or the hunter said yes. */
export function confirmLeave(): boolean {
  if (!unsaved) return true
  const ok = window.confirm(`Leave without saving ${unsaved}?`)
  if (ok) unsaved = ''
  return ok
}

export function hasUnsavedDraft() { return !!unsaved }
