import { whenLabel } from './api'

/**
 * Team notes on photos: "Worth a look", who said it and when.
 *
 * Anyone except a viewer marks a photo from the photo viewer, with a short note or
 * none. The notes show under the photo, and the marked photos gather in the
 * "Worth a look" strips on Photos and on a camera's sheet, newest first.
 */

export const NOTE_MAX = 140

export type PhotoNote = {
  id: string
  image_id: string
  /** null: marked, nothing said. */
  text: string | null
  /** From the email until hunters can name themselves: pedro.garcia@… is "Pedro". */
  name: string
  created_at: string
  mine: boolean
  can_remove: boolean
}

/** GET /images/{id}/notes, and what adding or removing one answers. */
export type PhotoNotes = { image_id: string; can_add: boolean; notes: PhotoNote[] }

/** What POST /images/{id}/notes answers on top: who was told, and whether this save
 * kept a photo marked "nothing in it" (or was the same note saved a second time). */
export type NoteSaved = PhotoNotes & { told: number; muted: number; kept: boolean; again: boolean }

/**
 * A new note's id, made on the phone. Saving again after a weak signal swallowed the
 * answer then lands on the same note instead of a second one (and a second alert).
 * crypto.randomUUID is missing on a plain-http address, so the fallback builds the
 * same version-4 id from random bytes.
 */
export function newNoteId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

/** GET /photos/highlights: a feed item with its notes, most recently marked first. */
export type Highlight = {
  image_id: string
  file_url: string
  captured_at: string
  camera: string
  camera_id: string
  label: string
  species_id: string | null
  group_size: number | null
  notes_count: number
  /** Who said what it is, when a hunter fixed it ("Wrong?" in the viewer). */
  fixed_by?: string | null
  notes: PhotoNote[]
  marked_at: string
}

/** "Pedro · 21:40 · Big boar, third night running", or "… · Worth a look" with nothing said. */
export function noteLine(n: PhotoNote): string {
  return `${n.name} · ${whenLabel(n.created_at)} · ${n.text ?? 'Worth a look'}`
}

/**
 * A strip tile's words for a photo: the newest thing said about it, and who said it
 * and when ("Pedro · 21:40"), that note's time rather than the photo's. With nothing
 * said, who marked it last.
 */
export function noteSnippet(notes: PhotoNote[]): { said: string | null; who: string } {
  const said = [...notes].reverse().find((n) => n.text)
  const shown = said ?? notes[notes.length - 1]
  if (!shown) return { said: null, who: 'Worth a look' }
  return { said: said?.text ?? null, who: `${shown.name} · ${whenLabel(shown.created_at)}` }
}
