import maplibregl from 'maplibre-gl'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, thumbUrl } from '../api'
import { clock, linkArrow, minutesInto, type Replay, type ReplayNight, type ReplayVisit } from './activity'
import { validLngLat, type Camera, type LngLat } from './geometry'
import { setSource } from './layers'

const LOAD_TIMEOUT_MS = 30_000
const PRELOAD = 80
const PAINT_MS = 50
type Failure = Error & { offline?: boolean; timeout?: boolean }
const words = (what: string, e: Failure) => e.offline ? `No signal, so ${what} didn’t load.` : e.timeout ? `No answer from the server, so ${what} didn’t load.` : `Couldn’t load ${what}. ${e.message}`

/**
 * How long a visit stays up, in minutes of the night: about a second and a half of
 * playback at the fastest speed, and never less than half an hour, so a paused map
 * still shows what just happened.
 */
export const showFor = (speed: number) => Math.max(30, speed * 1.5)
const overlaps = (a: DOMRect, b: DOMRect) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
/** The part of the map a photo or a label can use: not under the round buttons on the
 * right, nor the scale at the top. */
function clearArea(map: maplibregl.Map): DOMRect {
  const r = map.getCanvas().getBoundingClientRect()
  return new DOMRect(r.left, r.top + 40, Math.max(0, r.width - 68), Math.max(0, r.height - 40))
}
type Side = 'above' | 'below' | 'right' | 'left'
const SIDES: Side[] = ['above', 'below', 'right', 'left']
/** Whether a line on screen passes through a box (the photo would hide the arrow). */
function crosses([x1, y1, x2, y2]: readonly [number, number, number, number], r: DOMRect): boolean {
  // Clip the segment to the box, one side at a time (Liang-Barsky).
  let t0 = 0, t1 = 1
  const dx = x2 - x1, dy = y2 - y1
  for (const [p, q] of [[-dx, x1 - r.left], [dx, r.right - x1], [-dy, y1 - r.top], [dy, r.bottom - y1]]) {
    if (p === 0) { if (q < 0) return false; continue }
    const t = q / p
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t } else { if (t < t0) return false; if (t < t1) t1 = t }
  }
  return true
}

type Shown = { visit: ReplayVisit; index: number; age: number }
// The marker element is MapLibre's to move (it owns its transform), so the pop's
// look, its arrival and its fading live on the card inside it.
type Pop = { marker: maplibregl.Marker; el: HTMLButtonElement; card: HTMLElement; key: string }

/**
 * Replay a night: the nights to pick from, the chosen night's visits, the clock and
 * its playback, and what is drawn on the map at the clock's time:
 *
 * - each camera's latest visit pops up at the camera as a small photo with the
 *   animal and the time, and fades once it is older than showFor(speed);
 * - a faint dashed arrow joins two cameras once the second visit has happened,
 *   brighter while it is new, with "likely went this way" beside it.
 *
 * Everything drawn is a function of the clock, so scrubbing back takes things off
 * the map again. When `on` goes false, all of it goes and the normal map is back.
 * `active` is false while something covers the replay bar: playback pauses.
 */
export function useReplay(map: maplibregl.Map | null, ready: boolean, on: boolean, active: boolean, cameras: Camera[], onPhoto: (index: number) => void) {
  const [nights, setNights] = useState<ReplayNight[] | null>(null)
  const [nightsErr, setNightsErr] = useState('')
  const [night, setNightState] = useState<string | null>(null)
  const [data, setData] = useState<Replay | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [t, setTState] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(10)
  const tRef = useRef(0)
  const nightsReq = useRef(0)
  const request = useRef(0)
  const pops = useRef(new Map<string, Pop>())
  const tags = useRef<{ key: string; markers: maplibregl.Marker[] }>({ key: '', markers: [] })
  const linksKey = useRef('')
  const layoutKey = useRef('')
  const photoRef = useRef(onPhoto); photoRef.current = onPhoto

  const total = data ? minutesInto(data.end, data.start) : 840
  const setT = useCallback((m: number) => { const next = Math.max(0, Math.min(total, m)); tRef.current = next; setTState(next) }, [total])

  const loadNights = useCallback(async () => {
    const id = ++nightsReq.current
    setNightsErr('')
    try {
      const list = await api<ReplayNight[]>('/map/replay/nights?limit=14', { timeoutMs: LOAD_TIMEOUT_MS })
      if (id !== nightsReq.current) return
      setNights(list)
      setNightState(current => current && list.some(n => n.night === current) ? current : list[0]?.night ?? null)
    } catch (e) { if (id === nightsReq.current) setNightsErr(words('the nights', e as Failure)) }
  }, [])
  const loadNight = useCallback(async (which: string) => {
    const id = ++request.current
    setLoading(true); setErr('')
    try {
      const next = await api<Replay>(`/map/replay?night=${which}`, { timeoutMs: LOAD_TIMEOUT_MS })
      if (id !== request.current) return
      setData(next)
      // Ready at once when it plays: the photos are small copies, cached for a year.
      for (const v of next.visits.slice(0, PRELOAD)) { const im = new Image(); im.src = thumbUrl(v.image_id) }
    } catch (e) { if (id === request.current) setErr(words('that night', e as Failure)) }
    finally { if (id === request.current) setLoading(false) }
  }, [])

  // The nights are asked for on every entry: after 06:00 there is a new last night.
  useEffect(() => {
    if (on) loadNights()
    else { nightsReq.current++; request.current++; setPlaying(false); setLoading(false); setErr(''); setNightsErr('') }
  }, [on, loadNights])
  useEffect(() => { if (on && night) loadNight(night) }, [on, night, loadNight])
  useEffect(() => { if (!active) setPlaying(false) }, [active])

  function setNight(next: string) { setPlaying(false); setData(null); tRef.current = 0; setTState(0); setNightState(next) }

  // Playback: the night's clock runs `speed` minutes per second of real time.
  useEffect(() => {
    if (!playing) return
    let frame = 0, last = performance.now(), painted = 0
    const step = (now: number) => {
      const next = Math.min(total, tRef.current + (now - last) / 1000 * speed)
      last = now
      tRef.current = next
      // The whole map page redraws on the clock, so about 20 times a second is enough:
      // at the fastest speed that is three minutes of the night per step.
      if (now - painted >= PAINT_MS || next >= total) { painted = now; setTState(next) }
      if (next >= total) { setPlaying(false); return }
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, speed, total])
  const play = useCallback(() => {
    if (playing) { setPlaying(false); return }
    if (tRef.current >= total) setT(0) // from the start again
    setPlaying(true)
  }, [playing, total, setT])

  const where = useMemo(() => {
    const out = new Map<string, { at: LngLat; name: string }>()
    for (const c of cameras) if (validLngLat(c.lon, c.lat)) out.set(c.id, { at: [c.lon!, c.lat!], name: c.name })
    return out
  }, [cameras])
  // Only visits at cameras on the map can pop up; the rest are counted apart.
  const visits = useMemo(() => (data?.visits ?? []).filter(v => where.has(v.camera_id)), [data, where])
  const offMap = (data?.visits.length ?? 0) - visits.length

  // ── drawing ──
  const clear = useCallback(() => {
    pops.current.forEach(p => p.marker.remove()); pops.current.clear()
    tags.current.markers.forEach(m => m.remove()); tags.current = { key: '', markers: [] }
    // Only an arrow drawn is cleared: an empty update is still work for the map. And
    // the page removes the map before this hook's own clean-up runs when it closes:
    // a removed map has no style left to clear.
    const drawn = linksKey.current !== ''
    linksKey.current = ''; layoutKey.current = ''
    if (drawn && map?.style && map.getSource('replay-links')) setSource(map, 'replay-links', [])
  }, [map])
  useEffect(() => { if (!on) clear() }, [on, clear])
  useEffect(() => () => clear(), [clear])

  useEffect(() => {
    if (!map || !ready || !on || !data) { if (map && ready && on) clear(); return }
    const span = showFor(speed)
    const shown = new Map<string, Shown>()
    visits.forEach((v, index) => {
      const age = t - minutesInto(v.at, data.start)
      if (age < 0 || age >= span) return
      const prev = shown.get(v.camera_id)
      if (!prev || age <= prev.age) shown.set(v.camera_id, { visit: v, index, age })
    })
    // Each camera's latest visit, popping up when it is new and fading as it ages.
    for (const [cam, pop] of pops.current) if (!shown.has(cam)) { pop.marker.remove(); pops.current.delete(cam) }
    for (const [cam, s] of shown) {
      const key = `${s.visit.image_id}-${s.visit.at}`
      let pop = pops.current.get(cam)
      if (!pop) {
        const el = document.createElement('button')
        el.type = 'button'; el.className = 'map-pop'
        el.innerHTML = '<span class="map-pop-card"><img alt="" draggable="false" decoding="async"><span class="map-pop-text"><b></b><small></small></span></span>'
        el.addEventListener('click', e => { e.stopPropagation(); setPlaying(false); photoRef.current(Number(el.dataset.index)) })
        pop = { el, card: el.firstElementChild as HTMLElement, key: '', marker: new maplibregl.Marker({ element: el, anchor: 'bottom', offset: [0, -18] }).setLngLat(where.get(cam)!.at).addTo(map) }
        pops.current.set(cam, pop)
      }
      if (pop.key !== key) {
        const v = s.visit, what = v.group_size > 1 ? `${v.label} ×${v.group_size}` : v.label
        pop.key = key
        pop.el.dataset.index = String(s.index)
        pop.el.querySelector('img')!.src = thumbUrl(v.image_id)
        pop.el.querySelector('b')!.textContent = what
        pop.el.querySelector('small')!.textContent = clock(Date.parse(v.at))
        pop.el.setAttribute('aria-label', `${what} at ${where.get(cam)?.name ?? 'a camera'}, ${clock(Date.parse(v.at))}. Open photo.`)
        pop.card.classList.remove('is-new'); void pop.card.offsetWidth; pop.card.classList.add('is-new')
      }
      const fade = Math.max(0, (s.age - span * .6) / (span * .4))
      pop.card.style.opacity = String(1 - fade * .8)
    }
    // Arrows once the second visit has happened: bright while new, faint after.
    const happened = data.links.map((l, i) => ({ l, i, age: t - minutesInto(l.to_at, data.start) }))
      .filter(x => x.age >= 0 && where.has(x.l.from_camera_id) && where.has(x.l.to_camera_id))
    const fresh = happened.filter(x => x.age < span)

    // Newest photo on top. Each goes beside its camera on the side away from a fresh
    // arrow, then any side that keeps it on the map, off a newer photo and off the
    // arrows. Worked out again only when what shows changes, or the zoom.
    const newestFirst = [...shown].sort((a, b) => a[1].age - b[1].age)
    const layout = `${newestFirst.map(([cam, x]) => `${cam}${x.visit.image_id}`).join()}|${fresh.map(x => x.i).join()}@${Math.round(map.getZoom() * 4)}`
    if (layout !== layoutKey.current) {
      layoutKey.current = layout
      const at = (cam: string) => map.project(where.get(cam)!.at)
      const frame = clearArea(map)
      // The fresh arrows on screen, a little short of both cameras.
      const arrows = fresh.map(x => {
        const a = at(x.l.from_camera_id), b = at(x.l.to_camera_id), len = Math.hypot(b.x - a.x, b.y - a.y) || 1
        const k = Math.min(.4, 22 / len), ux = (b.x - a.x) * k, uy = (b.y - a.y) * k
        return [frame.left + a.x + ux, frame.top + a.y + uy, frame.left + b.x - ux, frame.top + b.y - uy] as const
      })
      const placed: DOMRect[] = []
      newestFirst.forEach(([cam], rank) => {
        const pop = pops.current.get(cam)!
        const link = [...fresh].reverse().find(x => x.l.to_camera_id === cam || x.l.from_camera_id === cam)
        const other = link && at(link.l.to_camera_id === cam ? link.l.from_camera_id : link.l.to_camera_id)
        const here = at(cam)
        const away: Side = !other ? 'above' : Math.abs(other.y - here.y) >= Math.abs(other.x - here.x)
          ? (other.y < here.y ? 'below' : 'above') : (other.x < here.x ? 'right' : 'left')
        pop.el.style.zIndex = String(10 - rank)
        const tryOn = (side: Side) => {
          pop.el.dataset.side = side
          const box = pop.card.getBoundingClientRect()
          const onMap = box.top >= frame.top && box.bottom <= frame.bottom && box.left >= frame.left && box.right <= frame.right
          const clear = !placed.some(p => overlaps(p, box))
          return { side, box, rank: onMap && clear ? (arrows.some(s => crosses(s, box)) ? 1 : 0) : 2 }
        }
        const tries = [away, ...SIDES.filter(s => s !== away)].map(tryOn)
        const best = tries.reduce((x, y) => y.rank < x.rank ? y : x)
        pop.el.dataset.side = best.side
        placed.push(best.box)
      })
    }

    const key = happened.map(x => `${x.i}${x.age < span ? '+' : ''}`).join(',')
    if (key !== linksKey.current) {
      linksKey.current = key
      setSource(map, 'replay-links', happened.flatMap(x => linkArrow(where.get(x.l.from_camera_id)!.at, where.get(x.l.to_camera_id)!.at, x.age < span ? .9 : .4)))
    }
    const tagKey = `${fresh.map(x => x.i).join(',')}|${layoutKey.current}`
    if (tagKey !== tags.current.key) {
      tags.current.markers.forEach(m => m.remove())
      // Beside the arrow, clear of the cameras, the photos and the round buttons: the
      // middle first, then a third of the way from either end, on either side. Where
      // none is clear, no label (the bar says what a dashed arrow means).
      const frame = clearArea(map)
      const taken = [...document.querySelectorAll('.map-pin .map-pin-icon, .map-pop-card')].map(el => el.getBoundingClientRect())
      tags.current = { key: tagKey, markers: fresh.slice(-2).flatMap(x => {
        const a = where.get(x.l.from_camera_id)!.at, b = where.get(x.l.to_camera_id)!.at
        const pa = map.project(a), pb = map.project(b), len = Math.hypot(pb.x - pa.x, pb.y - pa.y)
        if (len < 110) return []
        const el = document.createElement('span')
        el.className = 'map-link-tag'
        // The photos at both ends already say which animal.
        el.textContent = 'Likely went this way'
        el.title = `${x.l.label}: likely went this way. A guess.`
        const marker = new maplibregl.Marker({ element: el }).setLngLat(a).addTo(map)
        const half = el.getBoundingClientRect().width / 2 - 8
        for (const f of [.5, .35, .65]) for (const side of [1, -1]) for (const shift of [0, -half, half]) {
          marker.setLngLat([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f])
          marker.setOffset([(pa.y - pb.y) / len * 24 * side + shift, (pb.x - pa.x) / len * 24 * side])
          const box = el.getBoundingClientRect()
          const inside = box.left >= frame.left && box.right <= frame.right && box.top >= frame.top && box.bottom <= frame.bottom
          if (inside && !taken.some(r => overlaps(r, box))) { taken.push(box); return [marker] }
        }
        marker.remove()
        return []
      }) }
    }
  }, [map, ready, on, data, visits, t, speed, where, clear])

  const soFar = data ? visits.filter(v => minutesInto(v.at, data.start) <= t).length : 0
  return {
    nights, nightsErr, reloadNights: loadNights, night, setNight, data, visits, offMap, loading, err,
    reload: () => { if (night) loadNight(night) }, t, setT, total, playing, play, speed, setSpeed, soFar,
  }
}
