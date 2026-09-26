import type maplibregl from 'maplibre-gl'

/**
 * Stand and camera pins: what each one is, which ones a tap lands on, and which
 * names have room to show.
 */
export type PinKind = 'stand' | 'camera'
export type PinRef = { kind: PinKind; id: string; name: string; lon: number; lat: number }
export type Pin = { marker: maplibregl.Marker; pin: PinRef }

export const PIN_ICONS: Record<PinKind, string> = {
  stand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M5 21V8l7-5 7 5v13M4 11h16M8 21v-6h8v6"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="6" width="18" height="14" rx="3"/><circle cx="12" cy="13" r="4"/><path d="M8 6V3h8v3"/></svg>',
}

const within = (r: DOMRect, x: number, y: number) => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom
const overlaps = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom

/**
 * Every pin whose tap target covers this point on the screen, cameras first.
 *
 * A camera usually sits a few metres from its stand, so at estate zoom their pins
 * overlap and whichever is on top would swallow every tap. More than one here means
 * the page asks which, rather than guessing.
 */
export function pinsAt(pins: Pin[], x: number, y: number): PinRef[] {
  return pins
    .filter(({ marker }) => within(marker.getElement().getBoundingClientRect(), x, y))
    .map(p => p.pin)
    .sort((a, b) => a.kind === b.kind ? a.name.localeCompare(b.name) : a.kind === 'camera' ? -1 : 1)
}

/**
 * Keep names off other pins and other names, so the map reads as pins with names
 * rather than a pile of text. A name that would land on something tries the other
 * side of its pin first (a camera's goes above, a stand's below), and only then
 * waits for more room. The selected pin's name always shows, then the cameras'
 * (what the team opens the map for), then the stands'. Hidden with visibility, so
 * each name keeps its size and can be measured again.
 */
export function declutterLabels(pins: Pin[]) {
  const els = pins.map(p => p.marker.getElement())
  const icons = els.map(el => (el.querySelector('.map-pin-icon') ?? el).getBoundingClientRect())
  const rank = (el: HTMLElement) => el.classList.contains('is-selected') ? 0 : el.dataset.kind === 'camera' ? 1 : 2
  const order = els.map((_, i) => i).sort((a, b) => rank(els[a]) - rank(els[b]))
  const kept: DOMRect[] = []
  for (const i of order) {
    const label = els[i].querySelector<HTMLElement>('.map-pin-label')
    if (!label) continue
    label.classList.remove('is-clashing', 'is-flipped')
    let r = label.getBoundingClientRect()
    // Not shown at this zoom: nothing to decide.
    if (!r.width) continue
    const clashes = (box: DOMRect) => rank(els[i]) > 0 && (icons.some((b, j) => j !== i && overlaps(box, b)) || kept.some(k => overlaps(box, k)))
    if (clashes(r)) {
      label.classList.add('is-flipped')
      r = label.getBoundingClientRect()
      if (clashes(r)) { label.classList.remove('is-flipped'); label.classList.add('is-clashing'); continue }
    }
    kept.push(r)
  }
}
