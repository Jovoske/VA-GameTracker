import { useLayoutEffect, useRef } from 'react'
import { PARTS, PERIODS, circleRadius, legendSizes, rateWords, type Activity, type ActivityCamera, type ActivityFilters } from './activity'

/**
 * The activity view's controls, docked under the map: how far back, which part of
 * the night, which animal, and what the circles mean. Every control is a
 * glove-sized chip, and the answer is on the map, not in here.
 */
export function ActivityBar({ filters, onFilters, data, onClose }: {
  filters: ActivityFilters
  onFilters: (next: ActivityFilters) => void
  data: Activity | null
  onClose: () => void
}) {
  const options = data?.species_options ?? []
  // The chosen animal keeps its chip even in a period it wasn't seen in.
  const chosen = filters.species !== 'all' && !options.some(o => o.species_id === filters.species)
    ? [{ species_id: filters.species, label: data?.species === filters.species && data.species_label ? data.species_label : 'This animal', visits: 0 }] : []
  const chips = [...chosen, ...options]
  const rates = (data?.cameras ?? []).flatMap(c => c.per_night ? [c.per_night] : [])
  const top = Math.max(0, ...rates)
  const [small, big] = legendSizes(top)
  const key = (rate: number, words: string) => { const r = circleRadius(rate), d = Math.ceil(r * 2 + 4)
    return <span className="mode-legend-key"><svg width={d} height={d} aria-hidden="true"><circle className="mode-legend-dot" cx={d / 2} cy={d / 2} r={r} /></svg>{words}</span> }
  return <section className="mode-bar mode-bar--activity" aria-label="Activity">
    <div className="mode-bar-row">
      <div className="mode-seg" role="radiogroup" aria-label="How far back">
        {PERIODS.map(p => <button key={p.id} type="button" role="radio" aria-checked={filters.nights === p.id} onClick={() => onFilters({ ...filters, nights: p.id })}>{p.label}</button>)}
      </div>
      <button type="button" className="mode-bar-x" aria-label="Close activity, back to the camera photos" onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    <div className="mode-seg mode-seg--parts" role="radiogroup" aria-label="Part of the night">
      {PARTS.map(p => <button key={p.id} type="button" role="radio" aria-checked={filters.part === p.id} onClick={() => onFilters({ ...filters, part: p.id })}>
        <span>{p.label}</span><small>{p.hours}</small>
      </button>)}
    </div>
    <div className="mode-chips" role="radiogroup" aria-label="Which animal">
      <button type="button" role="radio" aria-checked={filters.species === 'all'} onClick={() => onFilters({ ...filters, species: 'all' })}>All animals</button>
      {chips.map(o => <button key={o.species_id} type="button" role="radio" aria-checked={filters.species === o.species_id} onClick={() => onFilters({ ...filters, species: o.species_id! })}>{o.label}</button>)}
    </div>
    <div className="mode-legend" aria-label="What the circles mean">
      {/* Circles stop growing at TOP_RATE, so a busier camera is "10+" in the key. */}
      {key(small, rateWords(small))}{key(big, top > big ? `${big}+ a night` : rateWords(big))}
      <small>Circle size: visits a night the camera was working. Nights it wasn’t are left out.</small>
    </div>
  </section>
}

/** What one camera's circle says, in a line, with the numbers behind a fold. */
export function ActivityCard({ camera, data, onOpen, onClose, onHeight }: {
  camera: ActivityCamera
  data: Activity
  onOpen: () => void
  onClose: () => void
  /** The card's height, so the round buttons on the left can ride above it. */
  onHeight: (px: number) => void
}) {
  const root = useRef<HTMLElement>(null)
  const heightRef = useRef(onHeight); heightRef.current = onHeight
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const watch = new ResizeObserver(() => heightRef.current(el.offsetHeight + 12))
    watch.observe(el)
    return () => { watch.disconnect(); heightRef.current(0) }
  }, [])
  const c = camera
  // The top three and how many more: the whole list is behind "Numbers".
  const mix = data.species === 'all' && c.by_species.length > 1
    ? c.by_species.slice(0, 3).map(s => `${s.label} ${s.visits}`).join(' · ') + (c.by_species.length > 3 ? ` · ${c.by_species.length - 3} more` : '') : null
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const numbers = [
    `${plural(c.visits, 'visit')} over ${plural(c.watched_nights, 'night')} it was working${c.per_night ? `, ${rateWords(c.per_night).replace('1 every', 'one every')}` : ''}.`,
    c.blind_nights ? `Left out: ${plural(c.blind_nights, 'night')} it wasn’t working or was out of photo credits.` : null,
    c.checking_nights ? `Still checking the photos from ${plural(c.checking_nights, 'night')}.` : null,
    c.peak ? `Busiest ${c.peak} h.` : null,
    data.species === 'all' && c.by_species.length > 3 ? c.by_species.map(s => `${s.label} ${s.visits}`).join(' · ') : null,
  ].filter(Boolean)
  return <section ref={root} className="act-card" aria-label={`Activity at ${c.name}`} aria-live="polite">
    <div className="act-card-head">
      <h2>{c.name}</h2>
      <button type="button" className="bsheet-close" aria-label="Close" onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    <p className="act-card-read">{c.read}</p>
    {mix && <p className="act-card-mix">{mix}</p>}
    <div className="act-card-foot">
      {c.per_night != null ? <details className="act-card-numbers">
        <summary>Numbers</summary>
        {numbers.map(line => <p key={line}>{line}</p>)}
      </details> : <span />}
      <button type="button" className="map-button map-button--primary act-card-open" onClick={onOpen}>Open camera</button>
    </div>
  </section>
}
