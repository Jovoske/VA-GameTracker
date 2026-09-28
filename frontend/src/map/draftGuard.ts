/**
 * An outline that isn't saved yet, so leaving the map can ask first.
 *
 * The map page holds navigation back with react-router's useBlocker, which covers
 * the tabs, the browser's Back and the phone's back gesture alike, and the browser
 * gets a beforeunload for reloads and closing the tab (B-12). Signing out isn't a
 * navigation the router can hold (the token goes first), so it asks here itself.
 */
import { t } from '../i18n'

let unsaved = ''

export function setUnsavedDraft(what: string) { unsaved = what }

/** True when it is fine to leave: nothing unsaved, or the hunter said yes. */
export function confirmLeave(): boolean {
  if (!unsaved) return true
  const ok = window.confirm(t('map.leaveUnsaved', { what: unsaved }))
  if (ok) unsaved = ''
  return ok
}

export function hasUnsavedDraft() { return !!unsaved }
