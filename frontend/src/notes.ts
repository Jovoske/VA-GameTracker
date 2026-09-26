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
  notes: PhotoNote[]
  marked_at: string
}

/** "Pedro · 21:40 · Big boar, third night running", or "… · Worth a look" with nothing said. */
export function noteLine(n: PhotoNote): string {
  return `${n.name} · ${whenLabel(n.created_at)} · ${n.text ?? 'Worth a look'}`
}

/** The strip's one line for a photo: the newest thing said about it. */
export function noteSnippet(notes: PhotoNote[]): string {
  const said = [...notes].reverse().find((n) => n.text)
  const last = notes[notes.length - 1]
  if (said) return `${said.name}: ${said.text}`
  return last ? `${last.name} marked it` : 'Worth a look'
}
