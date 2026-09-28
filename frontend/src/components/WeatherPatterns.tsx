import { WindIcon } from '@phosphor-icons/react/dist/csr/Wind'
import { GaugeIcon } from '@phosphor-icons/react/dist/csr/Gauge'
import { TrendUpIcon } from '@phosphor-icons/react/dist/csr/TrendUp'
import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { CloudIcon } from '@phosphor-icons/react/dist/csr/Cloud'
import { DropIcon } from '@phosphor-icons/react/dist/csr/Drop'
import { ThermometerIcon } from '@phosphor-icons/react/dist/csr/Thermometer'
import { SunHorizonIcon } from '@phosphor-icons/react/dist/csr/SunHorizon'
import type { Icon } from '@phosphor-icons/react'
import { type Key, fmtDate, fmtNumber, t } from '../i18n'

/** A night's date ("2026-08-14") as the language writes one: "14 Aug", with the
 *  year only when it isn't this year's. */
const dayOf = (iso: string): string => {
  const at = `${iso}T12:00:00`
  const thisYear = iso.slice(0, 4) === String(new Date().getFullYear())
  return fmtDate(at, thisYear ? { day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: 'numeric' })
}

type Bucket = { label: string; rate: number; days?: number; min?: number; max?: number }
export type Driver = {
  factor: string
  key?: string
  sample_nights: number
  // low, mid and high; or only low and high when most nights read the same (dry
  // nights against wet ones).
  buckets: Bucket[]
  // Held up against the same nights shuffled: a finding. False: could be chance.
  // Only the high end against the low end is ever tested, never the middle bar.
  beats_chance?: boolean
  // Which end had more visits: the one direction a finding may state.
  favours_high?: boolean
}
// Why a condition has no bars: too few nights, nights enough that hardly differ (three
// wet ones in ninety), or the weather history couldn't be had.
type VarStatus = 'ok' | 'insufficient' | 'no_spread' | 'unavailable'
export type PatternScope = {
  key: string; label: string; drivers: Driver[]; total_nights: number; sightings: number
  status?: Record<string, VarStatus>
}
export type Patterns = {
  scopes: PatternScope[]; nights: number; range?: [string, string]
  // Whether the differences were tested against chance, and against how many shuffles.
  tested?: boolean; shuffles?: number
}

// `labels` name the three bars; `pair` the two when most nights read the same.
// `phrases` finish the sentence "More wild boar … than …" for the low and the high
// end, the only two a finding compares. `flat` is what a card says when the nights
// hardly differ.
const FACTORS: { key: string; title: Key; Icon: Icon; labels: [Key, Key, Key]; pair?: [Key, Key]; phrases: [Key, Key]; flat: Key; meaning: Key }[] = [
  { key: 'wind', title: 'weather.wind', Icon: WindIcon, labels: ['weather.wind.low', 'weather.between', 'weather.wind.high'],
    phrases: ['weather.wind.whenLow', 'weather.wind.whenHigh'], flat: 'weather.wind.flat', meaning: 'weather.wind.meaning' },
  { key: 'pressure', title: 'weather.pressure', Icon: GaugeIcon, labels: ['weather.pressure.low', 'weather.between', 'weather.pressure.high'],
    phrases: ['weather.pressure.whenLow', 'weather.pressure.whenHigh'], flat: 'weather.pressure.flat', meaning: 'weather.pressure.meaning' },
  { key: 'pressure_trend', title: 'weather.trend', Icon: TrendUpIcon, labels: ['weather.trend.low', 'weather.between', 'weather.trend.high'],
    phrases: ['weather.trend.whenLow', 'weather.trend.whenHigh'], flat: 'weather.trend.flat', meaning: 'weather.trend.meaning' },
  { key: 'moon_illum', title: 'weather.moon', Icon: MoonIcon, labels: ['weather.moon.low', 'weather.between', 'weather.moon.high'],
    phrases: ['weather.moon.whenLow', 'weather.moon.whenHigh'], flat: 'weather.tooFew', meaning: 'weather.moon.meaning' },
  { key: 'temp', title: 'weather.temp', Icon: ThermometerIcon, labels: ['weather.temp.low', 'weather.between', 'weather.temp.high'],
    phrases: ['weather.temp.whenLow', 'weather.temp.whenHigh'], flat: 'weather.temp.flat', meaning: 'weather.temp.meaning' },
  { key: 'rain', title: 'weather.rain', Icon: DropIcon, labels: ['weather.rain.low', 'weather.between', 'weather.rain.high'], pair: ['weather.rain.low', 'weather.rain.high'],
    phrases: ['weather.rain.whenLow', 'weather.rain.whenHigh'], flat: 'weather.rain.flat', meaning: 'weather.rain.meaning' },
  { key: 'cloud', title: 'weather.cloud', Icon: CloudIcon, labels: ['weather.cloud.low', 'weather.between', 'weather.cloud.high'], pair: ['weather.cloud.low', 'weather.cloud.pairHigh'],
    phrases: ['weather.cloud.whenLow', 'weather.cloud.whenHigh'], flat: 'weather.cloud.flat', meaning: 'weather.cloud.meaning' },
  { key: 'darkness', title: 'weather.dark', Icon: SunHorizonIcon, labels: ['weather.dark.low', 'weather.between', 'weather.dark.high'],
    phrases: ['weather.dark.whenLow', 'weather.dark.whenHigh'], flat: 'weather.tooFew', meaning: 'weather.dark.meaning' },
]
type Factor = typeof FACTORS[number]

/** The pressure's phrases, and how each reads the second time in one sentence: "when
 *  the pressure is high than when it is low". */
const AGAIN: Partial<Record<Key, Key>> = {
  'weather.pressure.whenLow': 'weather.pressure.whenLowAgain',
  'weather.pressure.whenHigh': 'weather.pressure.whenHighAgain',
  'weather.pt.fallingFast': 'weather.pt.fallingFastAgain',
  'weather.pt.fallingGently': 'weather.pt.fallingGentlyAgain',
  'weather.pt.risingGently': 'weather.pt.risingGentlyAgain',
  'weather.pt.risingFast': 'weather.pt.risingFastAgain',
  'weather.pt.steady': 'weather.pt.steadyAgain',
  'weather.pt.steadyOrRising': 'weather.pt.steadyOrRisingAgain',
  'weather.pt.steadyOrFalling': 'weather.pt.steadyOrFallingAgain',
  'weather.pt.changing': 'weather.pt.changingAgain',
}

function keyOf(driver: Driver) {
  return driver.key || ({ Moonlight: 'moon_illum', 'Moon illumination': 'moon_illum', 'Dark hours': 'darkness', 'Night duration': 'darkness', Wind: 'wind', Pressure: 'pressure', 'Pressure trend': 'pressure_trend', Temperature: 'temp', Rain: 'rain', 'Cloud cover': 'cloud' } as Record<string, string>)[driver.factor]
}

const oneDecimal = (n: number) => fmtNumber(n, { minimumFractionDigits: 1, maximumFractionDigits: 1 })

function range(key: string, bucket: Bucket) {
  if (bucket.min == null || bucket.max == null) return t('weather.noRange')
  const divisor = key === 'darkness' ? 60 : 1
  const unit = key === 'darkness' ? t('weather.hours') : ['moon_illum', 'cloud'].includes(key) ? '%' : key === 'temp' ? '°C' : key === 'wind' ? 'km/h' : key === 'rain' ? 'mm' : 'hPa'
  const number = (n: number) => fmtNumber(n / divisor, { maximumFractionDigits: 1 })
  return `${number(bucket.min)}–${number(bucket.max)} ${unit}`
}

function position(bucket: Bucket) {
  return bucket.label === 'low' ? 0 : bucket.label === 'high' ? 2 : 1
}

function bucketLabel(factor: Factor, bucket: Bucket, pair: boolean): string {
  const pos = position(bucket)
  if (factor.key !== 'pressure_trend' || bucket.min == null || bucket.max == null) {
    return t(pair && factor.pair ? factor.pair[pos === 0 ? 0 : 1] : factor.labels[pos])
  }
  if (bucket.max < 0) return t((['weather.pt.biggerFalls', 'weather.pt.moderateFalls', 'weather.pt.smallerFalls'] as const)[pos])
  if (bucket.min > 0) return t((['weather.pt.smallerRises', 'weather.pt.moderateRises', 'weather.pt.biggerRises'] as const)[pos])
  if (bucket.min === 0 && bucket.max === 0) return t('weather.pt.noChange')
  if (bucket.min === 0) return t('weather.pt.risesOrNone')
  if (bucket.max === 0) return t('weather.pt.fallsOrNone')
  return t('weather.pt.mix')
}

// The plain-sentence version of bucketLabel, for the low or the high end only:
// "More wild boar when it is windy than when the wind is light."
function endPhrase(factor: Factor, bucket: Bucket): Key {
  const end = bucket.label === 'high' ? 1 : 0
  if (factor.key !== 'pressure_trend' || bucket.min == null || bucket.max == null) return factor.phrases[end]
  if (bucket.max < 0) return (['weather.pt.fallingFast', 'weather.pt.fallingGently'] as const)[end]
  if (bucket.min > 0) return (['weather.pt.risingGently', 'weather.pt.risingFast'] as const)[end]
  if (bucket.min === 0 && bucket.max === 0) return 'weather.pt.steady'
  if (bucket.min === 0) return 'weather.pt.steadyOrRising'
  if (bucket.max === 0) return 'weather.pt.steadyOrFalling'
  return 'weather.pt.changing'
}

function more(factor: Factor, found: { more: Bucket; less: Bucket }) {
  const a = endPhrase(factor, found.more)
  const b = endPhrase(factor, found.less)
  const again = AGAIN[a] && AGAIN[b] ? AGAIN[b]! : b
  return t('weather.than', { a: t(a), b: t(again) })
}

// The bars, and whether the two ends a finding compares are there and apart.
function compare(driver?: Driver) {
  const buckets = ['low', 'mid', 'high'].map(label => driver?.buckets.find(b => b.label === label)).filter((b): b is Bucket => !!b && Number.isFinite(b.rate))
  const low = buckets.find(b => b.label === 'low')
  const high = buckets.find(b => b.label === 'high')
  const max = Math.max(...buckets.map(b => b.rate), 0)
  const complete = !!low && !!high
  // Overlapping ends do not tell two conditions apart, whatever the counts.
  const separated = complete && (low.max == null || high.min == null || low.max < high.min)
  const differs = buckets.some(b => b.rate !== buckets[0].rate)
  return { buckets, low, high, max, complete, separated, differs, pair: complete && buckets.length === 2 }
}

/** The one end that stood out against the other AND held up against chance, if
 *  any. Only the two ends were tested, so the middle bar is never a finding, even
 *  when it is the tallest. */
function finding(driver?: Driver) {
  const { low, high, separated } = compare(driver)
  if (!driver?.beats_chance || !low || !high || !separated || low.rate === high.rate) return null
  const upHigh = driver.favours_high ?? high.rate > low.rate
  return upHigh ? { more: high, less: low } : { more: low, less: high }
}

function FactorCard({ factor, driver, status }: { factor: Factor; driver?: Driver; status?: VarStatus }) {
  const { key, Icon, meaning } = factor
  const title = t(factor.title)
  const { buckets, max, complete, separated, differs, pair } = compare(driver)
  const found = finding(driver)
  // Bars that did not beat chance are said to be what they are: a difference this
  // size turns up in shuffled nights too, so it is not a finding (audit G-04, J-09).
  const takeaway = status === 'unavailable' ? t('weather.unavailable')
    : status === 'no_spread' && !complete ? t(factor.flat)
    : !complete ? t('weather.notEnough')
    : !separated ? t('weather.tooClose')
    : found ? t('weather.moreVisits', { more: more(factor, found) })
    : differs ? t('weather.chance')
    : t('weather.noDifference')

  return <article className="weather-card" aria-labelledby={`factor-${key}`}>
    <div className="weather-card-heading"><Icon size={23} aria-hidden="true" /><h3 id={`factor-${key}`}>{title}</h3></div>
    <p className="weather-takeaway">{takeaway}</p>
    {complete && <>
      <div className="weather-bars" role="img" aria-label={t('weather.barsLabel', { title, bars: buckets.map(b => `${bucketLabel(factor, b, pair)}: ${oneDecimal(b.rate)}`).join('. ') })}>
        {buckets.map(b => <div className="weather-bar-row" key={b.label} aria-hidden="true">
          <div className="weather-bar-label"><span>{bucketLabel(factor, b, pair)}</span><strong>{oneDecimal(b.rate)}</strong></div>
          <div className="weather-bar-track"><div className={`weather-bar-fill${b === found?.more ? ' is-highest' : ''}`} style={{ width: `${max > 0 ? b.rate / max * 100 : 0}%` }} /></div>
        </div>)}
      </div>
      <p className="weather-bar-caption">{t('weather.barCaption', { count: driver?.sample_nights ?? 0 })}</p>
    </>}
    <details className="weather-details">
      <summary>{complete ? t('weather.whatBars') : t('weather.whatMeasures', { what: title.toLocaleLowerCase() })}</summary>
      <p>{t(meaning)}</p>
      {complete && <table><caption>{t('weather.tableCaption')}</caption><thead><tr><th>{t('weather.bar')}</th><th>{t('weather.range')}</th><th>{t('weather.nights')}</th></tr></thead><tbody>{buckets.map(b => <tr key={b.label}><th>{bucketLabel(factor, b, pair)}</th><td>{range(key, b)}</td><td>{b.days ?? '—'}</td></tr>)}</tbody></table>}
    </details>
  </article>
}

export default function WeatherPatterns({ patterns, scope, onScope, error, loading, retry }: { patterns: Patterns | null; scope: string; onScope: (key: string) => void; error: string; loading: boolean; retry: () => void }) {
  const selected = patterns?.scopes.find(s => s.key === scope) || patterns?.scopes[0]
  const driverFor = (factor: Factor) => selected?.drivers.find(d => keyOf(d) === factor.key)
  const subject = selected && selected.key !== 'all' ? selected.label.toLocaleLowerCase() : t('weather.animals')
  // A sentence only for a difference that held up against the same nights shuffled.
  // An older server did no such test, so nothing it sends is stated as a finding.
  const findings = FACTORS.flatMap(factor => {
    const found = finding(driverFor(factor))
    return found ? [{ key: factor.key, text: t('weather.finding', { subject, more: more(factor, found) }) }] : []
  })
  return <section className="insights-weather block" aria-labelledby="weather-heading">
    <h2 id="weather-heading" className="sect">{t('weather.title')}</h2>
    <p className="page-intro">{t('weather.intro')}</p>
    {error && <div className="status-panel" role="alert">{patterns ? t('weather.couldntUpdate') : t('weather.couldntLoad')}<button className="text-action" onClick={retry}>{t('common.retry')}</button></div>}
    {loading && !patterns && <p role="status" className="page-intro">{t('weather.checking')}</p>}
    {patterns && <>
      {patterns.scopes.length > 0 && <div className="weather-scopes" role="group" aria-label={t('weather.chooseAnimals')}>{patterns.scopes.map(s => <button key={s.key} aria-pressed={s.key === selected?.key} onClick={() => onScope(s.key)}>{s.label}</button>)}</div>}
      {!selected && <p className="weather-empty">{t('weather.noNights')}</p>}
      {selected && findings.length === 0 && <p className="weather-empty">{t('weather.nothingStands', { subject })}</p>}
      {selected && findings.length > 0 && <>
        <ul className="insights-findings" aria-label={t('weather.findingsFor', { subject: selected.label.toLocaleLowerCase() })}>
          {findings.map(f => <li key={f.key}>{f.text}</li>)}
        </ul>
        <p className="weather-bar-caption">{t('weather.heldUp', { count: patterns.shuffles ?? 200 })}</p>
      </>}
      {selected && <details className="weather-more" key={selected.key}>
        <summary>{t('weather.showNumbers')}</summary>
        <p className="weather-reading-guide">{t('weather.guide', { tested: patterns.tested ? t('weather.guideTested') : t('weather.guideUntested') })}</p>
        <div className="weather-grid">{FACTORS.map(factor => <FactorCard key={factor.key} factor={factor} driver={driverFor(factor)} status={selected.status?.[factor.key]} />)}</div>
        <p className="weather-bar-caption">{patterns.range
          ? t('weather.totalsRange', { label: selected.label, visits: fmtNumber(selected.sightings), count: selected.total_nights, from: dayOf(patterns.range[0]), to: dayOf(patterns.range[1]) })
          : t('weather.totals', { label: selected.label, visits: fmtNumber(selected.sightings), count: selected.total_nights })}</p>
      </details>}
    </>}
  </section>
}
