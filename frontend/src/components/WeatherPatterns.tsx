import { WindIcon } from '@phosphor-icons/react/dist/csr/Wind'
import { GaugeIcon } from '@phosphor-icons/react/dist/csr/Gauge'
import { TrendUpIcon } from '@phosphor-icons/react/dist/csr/TrendUp'
import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { CloudIcon } from '@phosphor-icons/react/dist/csr/Cloud'
import { DropIcon } from '@phosphor-icons/react/dist/csr/Drop'
import { ThermometerIcon } from '@phosphor-icons/react/dist/csr/Thermometer'
import { SunHorizonIcon } from '@phosphor-icons/react/dist/csr/SunHorizon'

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
const FACTORS = [
  { key: 'wind', title: 'Wind', Icon: WindIcon, labels: ['Light wind', 'In between', 'Strong wind'],
    phrases: ['when the wind is light', 'when it is windy'], flat: 'The wind hardly changed',
    meaning: 'Overnight wind speed. It says nothing about which way your scent goes; check the wind direction on the Map.' },
  { key: 'pressure', title: 'Air pressure', Icon: GaugeIcon, labels: ['Low pressure', 'In between', 'High pressure'],
    phrases: ['when the pressure is low', 'when the pressure is high'], flat: 'The pressure hardly changed',
    meaning: 'Overnight air pressure, as a barometer reads it.' },
  { key: 'pressure_trend', title: 'Pressure change', Icon: TrendUpIcon, labels: ['Smaller change', 'In between', 'Bigger change'],
    phrases: ['when the pressure barely moves', 'when the pressure moves a lot'], flat: 'The pressure hardly moved',
    meaning: 'How much the pressure moved since the night before. Below zero it fell, above zero it rose.' },
  { key: 'moon_illum', title: 'Moon', Icon: MoonIcon, labels: ['Dark moon', 'In between', 'Bright moon'],
    phrases: ['on a dark moon', 'on a bright moon'], flat: 'Too few nights to compare',
    meaning: 'How much of the moon was lit. Cloud and the moon being below the horizon still change how dark it is outside.' },
  { key: 'temp', title: 'Temperature', Icon: ThermometerIcon, labels: ['Cool', 'In between', 'Warm'],
    phrases: ['on cool nights', 'on warm nights'], flat: 'The temperature hardly changed',
    meaning: 'Average overnight temperature.' },
  { key: 'rain', title: 'Rain', Icon: DropIcon, labels: ['Dry', 'In between', 'Wet'], pair: ['Dry', 'Wet'],
    phrases: ['on dry nights', 'on wet nights'], flat: 'Too few wet nights to compare',
    meaning: 'How much rain fell overnight.' },
  { key: 'cloud', title: 'Cloud', Icon: CloudIcon, labels: ['Clear', 'In between', 'Overcast'], pair: ['Clear', 'Cloudy'],
    phrases: ['under clear skies', 'under cloud'], flat: 'Too few cloudy nights to compare',
    meaning: 'How much of the sky was covered overnight.' },
  { key: 'darkness', title: 'Dark hours', Icon: SunHorizonIcon, labels: ['Short nights', 'In between', 'Long nights'],
    phrases: ['on short nights', 'on long nights'], flat: 'Too few nights to compare',
    meaning: 'Sunset to sunrise. It changes with the season and includes twilight. Each night is compared with the weeks around it, so the season itself is not a finding.' },
]
type Factor = typeof FACTORS[number]

function keyOf(driver: Driver) {
  return driver.key || ({ Moonlight: 'moon_illum', 'Moon illumination': 'moon_illum', 'Dark hours': 'darkness', 'Night duration': 'darkness', Wind: 'wind', Pressure: 'pressure', 'Pressure trend': 'pressure_trend', Temperature: 'temp', Rain: 'rain', 'Cloud cover': 'cloud' } as Record<string, string>)[driver.factor]
}

function range(key: string, bucket: Bucket) {
  if (bucket.min == null || bucket.max == null) return 'Range unavailable'
  const divisor = key === 'darkness' ? 60 : 1
  const unit = key === 'darkness' ? 'hours' : ['moon_illum', 'cloud'].includes(key) ? '%' : key === 'temp' ? '°C' : key === 'wind' ? 'km/h' : key === 'rain' ? 'mm' : 'hPa'
  const number = (n: number) => (n / divisor).toLocaleString(undefined, { maximumFractionDigits: 1 })
  return `${number(bucket.min)}–${number(bucket.max)} ${unit}`
}

function position(bucket: Bucket) {
  return bucket.label === 'low' ? 0 : bucket.label === 'high' ? 2 : 1
}

function bucketLabel(factor: Factor, bucket: Bucket, pair: boolean) {
  const pos = position(bucket)
  if (factor.key !== 'pressure_trend' || bucket.min == null || bucket.max == null) {
    return pair && 'pair' in factor && factor.pair ? factor.pair[pos === 0 ? 0 : 1] : factor.labels[pos]
  }
  if (bucket.max < 0) return ['Bigger falls', 'Moderate falls', 'Smaller falls'][pos]
  if (bucket.min > 0) return ['Smaller rises', 'Moderate rises', 'Bigger rises'][pos]
  if (bucket.min === 0 && bucket.max === 0) return 'No change'
  if (bucket.min === 0) return 'Rises or no change'
  if (bucket.max === 0) return 'Falls or no change'
  return 'A mix of rises & falls'
}

// The plain-sentence version of bucketLabel, for the low or the high end only:
// "More wild boar when it is windy than when the wind is light."
function endPhrase(factor: Factor, bucket: Bucket) {
  const end = bucket.label === 'high' ? 1 : 0
  if (factor.key !== 'pressure_trend' || bucket.min == null || bucket.max == null) return factor.phrases[end]
  if (bucket.max < 0) return ['when the pressure is falling fast', 'when the pressure is falling gently'][end]
  if (bucket.min > 0) return ['when the pressure is rising gently', 'when the pressure is rising fast'][end]
  if (bucket.min === 0 && bucket.max === 0) return 'when the pressure is steady'
  if (bucket.min === 0) return 'when the pressure is steady or rising'
  if (bucket.max === 0) return 'when the pressure is steady or falling'
  return 'when the pressure is changing'
}

function more(factor: Factor, found: { more: Bucket; less: Bucket }) {
  const a = endPhrase(factor, found.more)
  const b = endPhrase(factor, found.less)
  const said = 'when the pressure is '
  return `${a} than ${a.startsWith(said) && b.startsWith(said) ? `when it is ${b.slice(said.length)}` : b}`
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
  const { key, title, Icon, meaning } = factor
  const { buckets, max, complete, separated, differs, pair } = compare(driver)
  const found = finding(driver)
  // Bars that did not beat chance are said to be what they are: a difference this
  // size turns up in shuffled nights too, so it is not a finding (audit G-04, J-09).
  const takeaway = status === 'unavailable' ? 'Weather history unavailable right now'
    : status === 'no_spread' && !complete ? factor.flat
    : !complete ? 'Not enough nights to compare yet'
    : !separated ? 'Too close to call'
    : found ? `More visits ${more(factor, found)}`
    : differs ? 'Could be chance'
    : 'No difference'

  return <article className="weather-card" aria-labelledby={`factor-${key}`}>
    <div className="weather-card-heading"><Icon size={23} aria-hidden="true" /><h3 id={`factor-${key}`}>{title}</h3></div>
    <p className="weather-takeaway">{takeaway}</p>
    {complete && <>
      <div className="weather-bars" role="img" aria-label={`${title}. Visits a night per camera. ${buckets.map(b => `${bucketLabel(factor, b, pair)}: ${b.rate.toFixed(1)}`).join('. ')}`}>
        {buckets.map(b => <div className="weather-bar-row" key={b.label} aria-hidden="true">
          <div className="weather-bar-label"><span>{bucketLabel(factor, b, pair)}</span><strong>{b.rate.toFixed(1)}</strong></div>
          <div className="weather-bar-track"><div className={`weather-bar-fill${b === found?.more ? ' is-highest' : ''}`} style={{ width: `${max > 0 ? b.rate / max * 100 : 0}%` }} /></div>
        </div>)}
      </div>
      <p className="weather-bar-caption">Visits a night per camera, over {driver?.sample_nights} watched nights</p>
    </>}
    <details className="weather-details">
      <summary>{complete ? 'What the bars measure' : `What ${title.toLowerCase()} measures`}</summary>
      <p>{meaning}</p>
      {complete && <table><caption>Conditions behind each bar</caption><thead><tr><th>Bar</th><th>Range</th><th>Nights</th></tr></thead><tbody>{buckets.map(b => <tr key={b.label}><th>{bucketLabel(factor, b, pair)}</th><td>{range(key, b)}</td><td>{b.days ?? '—'}</td></tr>)}</tbody></table>}
    </details>
  </article>
}

export default function WeatherPatterns({ patterns, scope, onScope, error, loading, retry }: { patterns: Patterns | null; scope: string; onScope: (key: string) => void; error: string; loading: boolean; retry: () => void }) {
  const selected = patterns?.scopes.find(s => s.key === scope) || patterns?.scopes[0]
  const driverFor = (factor: Factor) => selected?.drivers.find(d => keyOf(d) === factor.key)
  const subject = selected && selected.key !== 'all' ? selected.label.toLowerCase() : 'animals'
  // A sentence only for a difference that held up against the same nights shuffled.
  // An older server did no such test, so nothing it sends is stated as a finding.
  const findings = FACTORS.flatMap(factor => {
    const found = finding(driverFor(factor))
    return found ? [{ key: factor.key, text: `More ${subject} ${more(factor, found)}.` }] : []
  })
  return <section className="insights-weather block" aria-labelledby="weather-heading">
    <h2 id="weather-heading" className="sect">Weather and moon</h2>
    <p className="page-intro">Visits against the weather and the moon, on the nights the cameras were watching.</p>
    {error && <div className="status-panel" role="alert">{patterns ? 'Could not update the weather findings. Showing the previous ones.' : 'Could not load the weather findings.'}<button className="text-action" onClick={retry}>Retry</button></div>}
    {loading && !patterns && <p role="status" className="page-intro">Checking the weather on your busiest nights…</p>}
    {patterns && <>
      {patterns.scopes.length > 0 && <div className="weather-scopes" role="group" aria-label="Choose animals">{patterns.scopes.map(s => <button key={s.key} aria-pressed={s.key === selected?.key} onClick={() => onScope(s.key)}>{s.label}</button>)}</div>}
      {!selected && <p className="weather-empty">Not enough nights on the cameras yet. Findings appear as sightings build up.</p>}
      {selected && findings.length === 0 && <p className="weather-empty">No weather or moon pattern stands out from chance for {subject} yet. Keep the cameras running.</p>}
      {selected && findings.length > 0 && <>
        <ul className="insights-findings" aria-label={`Weather findings for ${selected.label.toLowerCase()}`}>
          {findings.map(f => <li key={f.key}>{f.text}</li>)}
        </ul>
        <p className="weather-bar-caption">These held up when the same nights were shuffled {patterns.shuffles ?? 200} times.</p>
      </>}
      {selected && <details className="weather-more" key={selected.key}>
        <summary>Show the numbers</summary>
        <p className="weather-reading-guide">Longer bar, more visits a night. {patterns.tested
          ? 'Only the top and bottom bars are compared. “Could be chance” means a gap that size turns up in shuffled nights too: it is not a finding.'
          : 'Not tested against chance: read these as counts, not findings.'} These are past counts, not tonight's odds.</p>
        <div className="weather-grid">{FACTORS.map(factor => <FactorCard key={factor.key} factor={factor} driver={driverFor(factor)} status={selected.status?.[factor.key]} />)}</div>
        <p className="weather-bar-caption">{selected.label}: {selected.sightings.toLocaleString()} visits over {selected.total_nights} watched nights{patterns.range && `, ${patterns.range[0]} to ${patterns.range[1]}`}.</p>
      </details>}
    </>}
  </section>
}
