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

const FACTORS = [
  { key: 'wind', title: 'Wind', Icon: WindIcon, labels: ['Lighter wind', 'In between', 'Stronger wind'],
    question: 'Do cameras see more animals when the wind is lighter or stronger?',
    meaning: 'This compares wind speed overnight. It does not tell you which way your scent will travel; check wind direction on the Map before choosing a spot.' },
  { key: 'pressure', title: 'Air pressure', Icon: GaugeIcon, labels: ['Lower pressure', 'In between', 'Higher pressure'],
    question: 'Do cameras see more animals when air pressure is lower or higher?',
    meaning: 'Air pressure is the weight of the air around us, measured by a barometer. Here we compare lower and higher readings in your camera history.' },
  { key: 'pressure_trend', title: 'Pressure changes', Icon: TrendUpIcon, labels: ['Smaller change', 'In between', 'Bigger change'],
    question: 'Does a change in air pressure go with more sightings?',
    meaning: 'This shows how much air pressure changed since the previous available reading. Below zero means it fell; above zero means it rose. A change alone does not tell us how animals will behave.' },
  { key: 'moon_illum', title: 'Moon', Icon: MoonIcon, labels: ['Less of the moon lit', 'In between', 'More of the moon lit'],
    question: 'Do cameras see more animals with a thinner or fuller moon?',
    meaning: 'A fuller moon has more of its face lit by the sun. Clouds and whether the moon is above the horizon also affect how light it is outside.' },
  { key: 'temp', title: 'Temperature', Icon: ThermometerIcon, labels: ['Cooler', 'In between', 'Warmer'],
    question: 'Do cooler or warmer conditions go with more sightings?',
    meaning: 'This compares average overnight temperatures in your camera history.' },
  { key: 'rain', title: 'Rain', Icon: DropIcon, labels: ['Less rain', 'In between', 'More rain'],
    question: 'Do cameras see more animals in drier or wetter conditions?',
    meaning: 'This compares the amount of rain overnight. A larger number means more rain fell.' },
  { key: 'cloud', title: 'Cloud cover', Icon: CloudIcon, labels: ['Fewer clouds', 'In between', 'More clouds'],
    question: 'Do clearer or cloudier skies go with more sightings?',
    meaning: 'This describes how much of the sky was covered by clouds overnight.' },
  { key: 'darkness', title: 'Night length', Icon: SunHorizonIcon, labels: ['Shorter nights', 'In between', 'Longer nights'],
    question: 'Do cameras record more animals when nights are longer?',
    meaning: 'This is the time from sunset to sunrise. It changes with the season and includes twilight, when it is still partly light.' },
]

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

function bucketLabel(key: string, bucket: Bucket, labels: string[]) {
  const position = bucket.label === 'low' ? 0 : bucket.label === 'high' ? 2 : 1
  if (key !== 'pressure_trend' || bucket.min == null || bucket.max == null) return labels[position]
  if (bucket.max < 0) return ['Bigger falls', 'Moderate falls', 'Smaller falls'][position]
  if (bucket.min > 0) return ['Smaller rises', 'Moderate rises', 'Bigger rises'][position]
  if (bucket.min === 0 && bucket.max === 0) return 'No change'
  if (bucket.min === 0) return 'Rises or no change'
  if (bucket.max === 0) return 'Falls or no change'
  return 'A mix of rises & falls'
}

function FactorCard({ factor, driver }: { factor: typeof FACTORS[number]; driver?: Driver }) {
  const { key, title, Icon, labels, question, meaning } = factor
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
  const clearLeader = complete && separated && max > min && leaders.length === 1
  const leader = clearLeader ? leaders[0] : null
  const takeaway = !complete ? 'No comparison available yet'
    : !separated ? 'These conditions overlap too much to pick a winner'
    : !leader ? 'No single condition stands out'
    : `Most sightings: ${bucketLabel(key, leader, labels).toLowerCase()}`

  return <article className="weather-card" aria-labelledby={`factor-${key}`}>
    <div className="weather-card-heading"><Icon size={23} aria-hidden="true" /><h3 id={`factor-${key}`}>{title}</h3><span className="weather-tag">{complete ? 'Past sightings' : 'No result shown'}</span></div>
    <p className="weather-question">{question}</p>
    <p className="weather-takeaway">{takeaway}</p>
    {complete ? <>
      <div className="weather-bars" role="img" aria-label={`${title}. Average camera sightings per day. ${buckets.map(b => `${bucketLabel(key, b, labels)}: ${b.rate.toFixed(1)}`).join('. ')}`}>
        {buckets.map(b => <div className="weather-bar-row" key={b.label} aria-hidden="true">
          <div className="weather-bar-label"><span>{bucketLabel(key, b, labels)}</span><strong>{b.rate.toFixed(1)}</strong></div>
          <div className="weather-bar-track"><div className={`weather-bar-fill${b === leader ? ' is-highest' : ''}`} style={{ width: `${max > 0 ? b.rate / max * 100 : 0}%` }} /></div>
        </div>)}
      </div>
      <p className="weather-bar-caption">Average camera sightings per day · {driver?.sample_nights} days compared</p>
      <p className="weather-use">{leader ? 'A clue to watch, not a reason on its own to choose a day.' : 'Use recent sightings to guide your plans for now.'}</p>
    </> : <p className="weather-empty">We cannot show a useful comparison for this animal group yet. That does not mean {title.toLowerCase()} has no effect.</p>}
    <details className="weather-details">
      <summary>{complete ? 'What this means & see the numbers' : `What does ${title.toLowerCase()} mean?`}</summary>
      <p>{meaning}</p>
      {complete && <table><caption>The conditions behind each bar</caption><thead><tr><th>Conditions</th><th>Range</th><th>Days</th></tr></thead><tbody>{buckets.map(b => <tr key={b.label}><th>{bucketLabel(key, b, labels)}</th><td>{range(key, b)}</td><td>{b.days ?? '—'}</td></tr>)}</tbody></table>}
    </details>
  </article>
}

export default function WeatherPatterns({ patterns, scope, onScope, error, loading, retry }: { patterns: Patterns | null; scope: string; onScope: (key: string) => void; error: string; loading: boolean; retry: () => void }) {
  const selected = patterns?.scopes.find(s => s.key === scope) || patterns?.scopes[0]
  const factorCard = (factor: typeof FACTORS[number]) => <FactorCard key={factor.key} factor={factor} driver={selected?.drivers.find(d => keyOf(d) === factor.key)} />
  return <section className="insights-weather block" aria-labelledby="weather-heading">
    <div className="insights-section-heading"><span className="insights-eyebrow">Learn from your cameras</span><h2 id="weather-heading">When do cameras see more animals?</h2></div>
    <p className="page-intro">Lighter wind or stronger wind? Thinner moon or fuller moon? See what went with more sightings on your land.</p>
    {error && <div className="status-panel" role="alert">{patterns ? 'Could not update the comparisons. These are the previous results.' : 'Could not load the weather comparisons.'}<button className="text-action" onClick={retry}>Retry comparisons</button></div>}
    {loading && !patterns && <p role="status" className="page-intro">Comparing your sightings with past weather…</p>}
    {patterns && <>
      {patterns.scopes.length > 0 && <div className="weather-scopes" role="group" aria-label="Choose animals to compare">{patterns.scopes.map(s => <button key={s.key} aria-pressed={s.key === selected?.key} onClick={() => onScope(s.key)}>{s.label}</button>)}</div>}
      <div className="weather-reading-guide"><span className="weather-mini-bars" aria-hidden="true"><i /><i /><i /></span><p><strong>Longer bar = more camera sightings.</strong><br />These are past counts, not your chance of seeing an animal tonight.</p></div>
      {!selected && <p className="weather-empty">There is not enough history to compare animal groups yet. Your comparisons will appear as sightings build up.</p>}
      <div className="weather-grid" key={selected?.key || 'empty'}>{FACTORS.slice(0, 4).map(factorCard)}</div>
      <details className="weather-more"><summary>Also explore rain, temperature, clouds & night length</summary><div className="weather-grid">{FACTORS.slice(4).map(factorCard)}</div></details>
      <details className="weather-method"><summary>How to read these comparisons</summary>
        <p>A sighting is an animal recorded by a camera. The same animal can be counted more than once. Each bar is an average per day, so groups with more days do not automatically get longer bars.</p>
        <p>Days run from 6 am to 6 am in estate time and include daytime sightings. Weather describes the overnight conditions. Days with no sightings are included, even if a camera was offline.</p>
        <p>Season, camera locations and repeated photos can also change the counts. These comparisons cannot tell us whether the weather caused the difference. Missing comparisons can mean limited sightings, missing weather or no clear result.</p>
        {selected && <p>{selected.label}: {selected.sightings.toLocaleString()} sightings across {selected.total_nights} days in the history.{patterns.range && ` Dates: ${patterns.range[0]} to ${patterns.range[1]}.`}</p>}
      </details>
    </>}
  </section>
}
