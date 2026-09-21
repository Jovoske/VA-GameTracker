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
  buckets: Bucket[]
}
export type PatternScope = {
  key: string; label: string; drivers: Driver[]; total_nights: number; sightings: number
}
export type Patterns = { scopes: PatternScope[]; nights: number; range?: [string, string] }

// `labels` name the three bars. `phrases` finish the sentence
// "More sightings …" for the same three conditions.
const FACTORS = [
  { key: 'wind', title: 'Wind', Icon: WindIcon, labels: ['Light wind', 'In between', 'Strong wind'],
    phrases: ['when the wind is light', 'in middling wind', 'when it is windy'],
    meaning: 'Overnight wind speed. It says nothing about which way your scent goes; check the wind direction on the Map.' },
  { key: 'pressure', title: 'Air pressure', Icon: GaugeIcon, labels: ['Low pressure', 'In between', 'High pressure'],
    phrases: ['when the pressure is low', 'in middling pressure', 'when the pressure is high'],
    meaning: 'Overnight air pressure, as a barometer reads it.' },
  { key: 'pressure_trend', title: 'Pressure change', Icon: TrendUpIcon, labels: ['Smaller change', 'In between', 'Bigger change'],
    phrases: ['when the pressure barely moves', 'in a middling change', 'when the pressure moves a lot'],
    meaning: 'How much the pressure moved since the night before. Below zero it fell, above zero it rose.' },
  { key: 'moon_illum', title: 'Moon', Icon: MoonIcon, labels: ['Dark moon', 'In between', 'Bright moon'],
    phrases: ['on a dark moon', 'with a half-lit moon', 'on a bright moon'],
    meaning: 'How much of the moon was lit. Cloud and the moon being below the horizon still change how dark it is outside.' },
  { key: 'temp', title: 'Temperature', Icon: ThermometerIcon, labels: ['Cool', 'In between', 'Warm'],
    phrases: ['on cool nights', 'on mild nights', 'on warm nights'],
    meaning: 'Average overnight temperature.' },
  { key: 'rain', title: 'Rain', Icon: DropIcon, labels: ['Dry', 'In between', 'Wet'],
    phrases: ['on dry nights', 'with a little rain', 'on wet nights'],
    meaning: 'How much rain fell overnight.' },
  { key: 'cloud', title: 'Cloud', Icon: CloudIcon, labels: ['Clear', 'In between', 'Overcast'],
    phrases: ['under clear skies', 'under broken cloud', 'under heavy cloud'],
    meaning: 'How much of the sky was covered overnight.' },
  { key: 'darkness', title: 'Dark hours', Icon: SunHorizonIcon, labels: ['Short nights', 'In between', 'Long nights'],
    phrases: ['on short nights', 'on middling nights', 'on long nights'],
    meaning: 'Sunset to sunrise. It changes with the season and includes twilight.' },
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

function bucketLabel(key: string, bucket: Bucket, labels: string[]) {
  const pos = position(bucket)
  if (key !== 'pressure_trend' || bucket.min == null || bucket.max == null) return labels[pos]
  if (bucket.max < 0) return ['Bigger falls', 'Moderate falls', 'Smaller falls'][pos]
  if (bucket.min > 0) return ['Smaller rises', 'Moderate rises', 'Bigger rises'][pos]
  if (bucket.min === 0 && bucket.max === 0) return 'No change'
  if (bucket.min === 0) return 'Rises or no change'
  if (bucket.max === 0) return 'Falls or no change'
  return 'A mix of rises & falls'
}

// The plain-sentence version of bucketLabel: "More sightings …".
function bucketPhrase(factor: Factor, bucket: Bucket) {
  const pos = position(bucket)
  if (factor.key !== 'pressure_trend' || bucket.min == null || bucket.max == null) return factor.phrases[pos]
  if (bucket.max < 0) return ['when the pressure is falling fast', 'when the pressure is falling', 'when the pressure is falling gently'][pos]
  if (bucket.min > 0) return ['when the pressure is rising gently', 'when the pressure is rising', 'when the pressure is rising fast'][pos]
  if (bucket.min === 0 && bucket.max === 0) return 'when the pressure is steady'
  if (bucket.min === 0) return 'when the pressure is steady or rising'
  if (bucket.max === 0) return 'when the pressure is steady or falling'
  return 'when the pressure is changing'
}

// Which of the three conditions clearly saw the most sightings, if any.
function compare(driver?: Driver) {
  const buckets = ['low', 'mid', 'high'].map(label => driver?.buckets.find(b => b.label === label)).filter((b): b is Bucket => !!b && Number.isFinite(b.rate))
  const max = Math.max(...buckets.map(b => b.rate), 0)
  const min = Math.min(...buckets.map(b => b.rate))
  const leaders = buckets.filter(b => b.rate === max)
  const complete = buckets.length === 3
  // Equal/overlapping ranges do not support a distinct winning condition, even
  // if sorting tied measurements happened to produce different sighting counts.
  const separated = complete && (leaders.length === 1
    ? buckets.every(b => b === leaders[0] || b.min == null || b.max == null || leaders[0].min == null || leaders[0].max == null || b.max < leaders[0].min || b.min > leaders[0].max)
    : buckets[0].max == null || buckets[2].min == null || buckets[0].max < buckets[2].min)
  const leader = complete && separated && max > min && leaders.length === 1 ? leaders[0] : null
  return { buckets, max, complete, separated, leader }
}

function FactorCard({ factor, driver }: { factor: Factor; driver?: Driver }) {
  const { key, title, Icon, labels, meaning } = factor
  const { buckets, max, complete, separated, leader } = compare(driver)
  const takeaway = !complete ? 'Not enough nights to compare yet'
    : !separated ? 'Too close to call'
    : !leader ? 'No difference worth noting'
    : `Most sightings: ${bucketLabel(key, leader, labels).toLowerCase()}`

  return <article className="weather-card" aria-labelledby={`factor-${key}`}>
    <div className="weather-card-heading"><Icon size={23} aria-hidden="true" /><h3 id={`factor-${key}`}>{title}</h3></div>
    <p className="weather-takeaway">{takeaway}</p>
    {complete && <>
      <div className="weather-bars" role="img" aria-label={`${title}. Sightings a day. ${buckets.map(b => `${bucketLabel(key, b, labels)}: ${b.rate.toFixed(1)}`).join('. ')}`}>
        {buckets.map(b => <div className="weather-bar-row" key={b.label} aria-hidden="true">
          <div className="weather-bar-label"><span>{bucketLabel(key, b, labels)}</span><strong>{b.rate.toFixed(1)}</strong></div>
          <div className="weather-bar-track"><div className={`weather-bar-fill${b === leader ? ' is-highest' : ''}`} style={{ width: `${max > 0 ? b.rate / max * 100 : 0}%` }} /></div>
        </div>)}
      </div>
      <p className="weather-bar-caption">Sightings a day, over {driver?.sample_nights} nights</p>
    </>}
    <details className="weather-details">
      <summary>{complete ? 'What the bars measure' : `What ${title.toLowerCase()} measures`}</summary>
      <p>{meaning}</p>
      {complete && <table><caption>Conditions behind each bar</caption><thead><tr><th>Bar</th><th>Range</th><th>Nights</th></tr></thead><tbody>{buckets.map(b => <tr key={b.label}><th>{bucketLabel(key, b, labels)}</th><td>{range(key, b)}</td><td>{b.days ?? '—'}</td></tr>)}</tbody></table>}
    </details>
  </article>
}

export default function WeatherPatterns({ patterns, scope, onScope, error, loading, retry }: { patterns: Patterns | null; scope: string; onScope: (key: string) => void; error: string; loading: boolean; retry: () => void }) {
  const selected = patterns?.scopes.find(s => s.key === scope) || patterns?.scopes[0]
  const driverFor = (factor: Factor) => selected?.drivers.find(d => keyOf(d) === factor.key)
  // One plain sentence per condition that clearly stood out.
  const findings = FACTORS.flatMap(factor => {
    const { leader } = compare(driverFor(factor))
    return leader ? [{ key: factor.key, text: `More sightings ${bucketPhrase(factor, leader)}.` }] : []
  })
  const subject = selected && selected.key !== 'all' ? selected.label.toLowerCase() : 'animals'
  return <section className="insights-weather block" aria-labelledby="weather-heading">
    <h2 id="weather-heading" className="sect">Weather and moon</h2>
    <p className="page-intro">What the weather was doing on the nights the cameras were busiest.</p>
    {error && <div className="status-panel" role="alert">{patterns ? 'Could not update the weather findings. Showing the previous ones.' : 'Could not load the weather findings.'}<button className="text-action" onClick={retry}>Retry</button></div>}
    {loading && !patterns && <p role="status" className="page-intro">Checking the weather on your busiest nights…</p>}
    {patterns && <>
      {patterns.scopes.length > 0 && <div className="weather-scopes" role="group" aria-label="Choose animals">{patterns.scopes.map(s => <button key={s.key} aria-pressed={s.key === selected?.key} onClick={() => onScope(s.key)}>{s.label}</button>)}</div>}
      {!selected && <p className="weather-empty">Not enough nights on the cameras yet. Findings appear as sightings build up.</p>}
      {selected && findings.length === 0 && <p className="weather-empty">No weather or moon pattern stands out for {subject} yet. Keep the cameras running.</p>}
      {selected && findings.length > 0 && <ul className="insights-findings" aria-label={`Weather findings for ${selected.label.toLowerCase()}`}>
        {findings.map(f => <li key={f.key}>{f.text}</li>)}
      </ul>}
      {selected && <details className="weather-more" key={selected.key}>
        <summary>Show the numbers</summary>
        <p className="weather-reading-guide">Longer bar, more sightings a day. These are past counts, not tonight's odds.</p>
        <div className="weather-grid">{FACTORS.map(factor => <FactorCard key={factor.key} factor={factor} driver={driverFor(factor)} />)}</div>
        <p className="weather-bar-caption">{selected.label}: {selected.sightings.toLocaleString()} sightings over {selected.total_nights} nights{patterns.range && `, ${patterns.range[0]} to ${patterns.range[1]}`}.</p>
      </details>}
    </>}
  </section>
}
