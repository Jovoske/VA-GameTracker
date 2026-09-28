import { useLayoutEffect, useRef } from 'react'
import { t } from '../i18n'
import { PARTS, PERIODS, circleRadius, legendSizes, rateWords, type Activity, type ActivityCamera, type ActivityFilters } from './activity'

/**
 * The activity view's controls, docked under the map: how far back, which part of
 * the night, which animal, and what the circles mean. Every control is a
 * glove-sized chip, and the answer is on the map, not in here.
 */
export function ActivityBar({ filters, onFilters, data, onClose, cardOpen = false }: {
  filters: ActivityFilters
  onFilters: (next: ActivityFilters) => void
  data: Activity | null
  onClose: () => void
  /** A camera's card is open over the map: on a short phone the filters step aside for it. */
  cardOpen?: boolean
}) {
  const options = data?.species_options ?? []
  // The chosen animal keeps its chip even in a period it wasn't seen in.
  const chosen = filters.species !== 'all' && !options.some(o => o.species_id === filters.species)
    ? [{ species_id: filters.species, label: data?.species === filters.species && data.species_label ? data.species_label : t('activity.thisAnimal'), visits: 0 }] : []
  const chips = [...chosen, ...options]
  const rates = (data?.cameras ?? []).flatMap(c => c.per_night ? [c.per_night] : [])
  const top = Math.max(0, ...rates)
  const [small, big] = legendSizes(top)
  const key = (rate: number, words: string) => { const r = circleRadius(rate), d = Math.ceil(r * 2 + 4)
    return <span className="mode-legend-key"><svg width={d} height={d} aria-hidden="true"><circle className="mode-legend-dot" cx={d / 2} cy={d / 2} r={r} /></svg>{words}</span> }
  return <section className={`mode-bar mode-bar--activity${cardOpen ? ' has-card' : ''}`} aria-label={t('view.activity')}>
    <div className="mode-bar-row">
      <div className="mode-seg" role="radiogroup" aria-label={t('activity.howFar')}>
        {PERIODS.map(p => <button key={p.id} type="button" role="radio" aria-checked={filters.nights === p.id} onClick={() => onFilters({ ...filters, nights: p.id })}>{t(p.label)}</button>)}
      </div>
      <button type="button" className="mode-bar-x" aria-label={t('activity.close')} onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    <div className="mode-seg mode-seg--parts" role="radiogroup" aria-label={t('activity.part')}>
      {PARTS.map(p => <button key={p.id} type="button" role="radio" aria-checked={filters.part === p.id} onClick={() => onFilters({ ...filters, part: p.id })}>
        <span>{t(p.label)}</span><small>{p.hours}</small>
      </button>)}
    </div>
    <div className="mode-chips" role="radiogroup" aria-label={t('activity.which')}>
      <button type="button" role="radio" aria-checked={filters.species === 'all'} onClick={() => onFilters({ ...filters, species: 'all' })}>{t('activity.allAnimals')}</button>
      {chips.map(o => <button key={o.species_id} type="button" role="radio" aria-checked={filters.species === o.species_id} onClick={() => onFilters({ ...filters, species: o.species_id! })}>{o.label}</button>)}
    </div>
    <div className="mode-legend" aria-label={t('activity.legend')}>
      {/* Circles stop growing at TOP_RATE, so a busier camera is "10+" in the key. */}
      {key(small, rateWords(small))}{key(big, top > big ? t('rate.plus', { n: big }) : rateWords(big))}
      <small>{t('activity.legendNote')}</small>
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
    ? c.by_species.slice(0, 3).map(s => `${s.label} ${s.visits}`).join(' · ') + (c.by_species.length > 3 ? ` · ${t('activity.more', { n: c.by_species.length - 3 })}` : '') : null
  const over = t('activity.overNights', { visits: t('common.visits', { count: c.visits }), nights: t('activity.nightsN', { count: c.watched_nights }) })
  const numbers = [
    c.per_night ? t('activity.overRate', { over, rate: rateWords(c.per_night, true) }) : `${over}.`,
    c.blind_nights ? t('activity.blind', { nights: t('activity.nightsN', { count: c.blind_nights }) }) : null,
    c.checking_nights ? t('activity.checking', { nights: t('activity.nightsN', { count: c.checking_nights }) }) : null,
    c.unreadable_nights ? t('activity.unreadable', { nights: t('activity.nightsN', { count: c.unreadable_nights }) }) : null,
    c.peak ? t('activity.busiest', { hours: c.peak }) : null,
    data.species === 'all' && c.by_species.length > 3 ? c.by_species.map(s => `${s.label} ${s.visits}`).join(' · ') : null,
  ].filter(Boolean)
  return <section ref={root} className="act-card" aria-label={t('activity.at', { name: c.name })} aria-live="polite">
    <div className="act-card-head">
      <h2>{c.name}</h2>
      <button type="button" className="bsheet-close" aria-label={t('common.close')} onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    <p className="act-card-read">{c.read}</p>
    {mix && <p className="act-card-mix">{mix}</p>}
    <div className="act-card-foot">
      {c.per_night != null ? <details className="act-card-numbers">
        <summary>{t('activity.numbers')}</summary>
        {numbers.map(line => <p key={line}>{line}</p>)}
      </details> : <span />}
      <button type="button" className="map-button map-button--primary act-card-open" onClick={onOpen}>{t('activity.openCamera')}</button>
    </div>
  </section>
}
