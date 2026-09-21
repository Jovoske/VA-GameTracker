import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, imageUrl } from '../api'
import Overlay from '../components/Overlay'
import PhotoLightbox from '../components/PhotoLightbox'
import WeatherPatterns, { type Patterns } from '../components/WeatherPatterns'
import { useRefetchOnReturn, useReveal } from '../hooks'
import './insights.css'

type Insights = {
  outlook: {
    date: string
    moon_phase: string
    moon_illum: number
    darkness_minutes: number | null
    sunset: string | null
    civil_twilight_end: string | null
  }[]
  composition: { label: string; count: number; top_camera: string | null }[]
  correlations: { kind?: string; statement: string; strength: number; sample: number }[]
}
type ClassImg = { image_id: string; file_url: string; captured_at: string; camera: string; group_size: number | null }
const dayName =(iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short' })
const dayNum = (iso: string) => new Date(iso + 'T12:00:00').getDate()
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '–'

// The numbers behind a finding, for the "Show the numbers" fold.
function backing(c: Insights['correlations'][number]) {
  const pct = Math.round(c.strength * 100)
  const sightings = `${c.sample.toLocaleString()} sightings`
  if (c.kind === 'time') return `${pct}% of ${sightings} fell in these hours.`
  if (c.kind === 'location') return `${pct}% of ${sightings} were on these two cameras.`
  return `From ${sightings}.`
}

export default function Insights() {
  const [d, setD] = useState<Insights | null>(null)
  const [err, setErr] = useState('')
  const [classErr, setClassErr] = useState('')
  const classRequest = useRef(0)
  const [openClass, setOpenClass] = useState<string | null>(null)
  const [classImgs, setClassImgs] = useState<ClassImg[] | null>(null)
  // Index into classImgs of the photo open in the viewer.
  const [zoom, setZoom] = useState<number | null>(null)
  const [pat, setPat] = useState<Patterns | null>(null)
  const [patScope, setPatScope] = useState('all')
  const [patErr, setPatErr] = useState('')
  const [patLoading, setPatLoading] = useState(true)
  const patternRequest = useRef(0)
  const [showBars, setShowBars] = useState(false)
  // Bars grow from their baseline once the numbers land, then track the data
  // from there: a refetch slides them to the new value rather than cutting.
  const grown = useReveal(!!d)

  function loadPatterns() {
    const request = ++patternRequest.current
    setPatErr('')
    setPatLoading(true)
    api<Patterns>('/insights/patterns')
      .then(result => { if (request === patternRequest.current) setPat(result) })
      .catch(e => { if (request === patternRequest.current) setPatErr(e.message) })
      .finally(() => { if (request === patternRequest.current) setPatLoading(false) })
  }
  function load() {
    setErr('')
    api<Insights>('/insights').then(setD).catch((e) => setErr(e.message))
    loadPatterns()
  }
  useEffect(load, [])
  useRefetchOnReturn(load, 120_000)

  async function openClassImages(label: string) {
    const request = ++classRequest.current
    setClassErr('')
    setOpenClass(label)
    setClassImgs(null)
    try {
      const photos = await api<ClassImg[]>('/insights/class?label=' + encodeURIComponent(label))
      if (request === classRequest.current) setClassImgs(photos)
    } catch {
      if (request === classRequest.current) setClassErr('Could not load the photos. Check your connection and try again.')
    }
  }
  function closeClass() {
    classRequest.current++
    setOpenClass(null)
    setClassImgs(null)
  }
  // During a rolling update the old API may still send untyped moon summaries.
  // Typed location summaries can legitimately include camera names like Moon Meadow.
  const findings = d?.correlations.filter(c => c.kind ? c.kind !== 'moon' : !/moon|bright nights|dark nights/i.test(c.statement)) || []
  const maxCount = d ? Math.max(...d.composition.map((x) => x.count), 1) : 1

  return (
    <div className="insights-page">
      <div className="insights-header"><div><h1 className="page-title">Insights</h1><p className="page-intro">What your cameras have seen.</p></div><Link to="/" className="insights-tonight">Plan tonight <span aria-hidden="true">↗</span></Link></div>
      {err && <div className="status-panel" role="alert">{d ? 'Could not refresh the findings. Showing the last ones.' : 'Could not load the findings.'}<button className="text-action" onClick={load}>Retry</button></div>}
      {!d && !err && <p role="status" className="page-intro">Reading the cameras…</p>}

      {d && <div className="block insights-findings-block">
        <h2 className="sect">What the cameras have seen</h2>
        {findings.length === 0 && <p className="page-intro">Not enough sightings yet to say much. Keep the cameras running and the findings will come.</p>}
        {findings.length > 0 && <>
          <ul className="insights-findings">
            {findings.map((c, i) => <li key={i}>{c.statement}</li>)}
          </ul>
          <details className="insights-numbers">
            <summary>Show the numbers</summary>
            <ul>{findings.map((c, i) => <li key={i}><span>{c.statement}</span> {backing(c)}</li>)}</ul>
          </details>
        </>}
      </div>}

      {d && d.composition && d.composition.length > 0 && (
        <div className="block">
          <h2 className="sect">Who is on the cameras</h2>
          <p className="page-intro">Tap a row to see the photos.</p>
          <div className="insights-classes">
            {d.composition.slice(0, 8).map((x) => (
              <div
                key={x.label}
                className="pressable insights-class"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                onClick={() => openClassImages(x.label)}
                title={`See the ${x.count} ${x.label} photos`}
              >
                <div className="insights-class-main">
                  <span className="insights-class-label">{x.label}</span>
                  <span className="insights-class-where">{x.count} {x.count === 1 ? 'photo' : 'photos'}{x.top_camera && `, mostly at ${x.top_camera}`}</span>
                </div>
                {showBars && <div className="insights-class-bar" aria-hidden="true">
                  <div className="bar-x" style={{ transform: `scaleX(${grown ? x.count / maxCount : 0})` }} />
                </div>}
                <span className="insights-class-chevron" aria-hidden="true">›</span>
              </div>
            ))}
          </div>
          <button type="button" className="insights-toggle" aria-pressed={showBars} onClick={() => setShowBars(v => !v)}>
            {showBars ? 'Hide the numbers' : 'Show the numbers'}
          </button>
        </div>
      )}

      <WeatherPatterns patterns={pat} scope={patScope} onScope={setPatScope} error={patErr} loading={patLoading} retry={loadPatterns} />

      {d && <div className="block insights-calendar">
        <h2 className="sect">Moon and last light this week</h2>
        <div className="moon-week">
          {d.outlook.map((o) => (
            <div
              key={o.date}
              className="moon-day"
            >
              <div className="moon-day-date">
                {dayName(o.date)} {dayNum(o.date)}
              </div>
              <div className="moon-illustration" aria-hidden="true">
                <MoonIcon size={26} weight={o.moon_illum > 65 ? 'fill' : 'regular'} />
              </div>
              <div className="moon-day-lit">
                {Math.round(o.moon_illum)}% lit
              </div>
              <div className="moon-day-phase">{o.moon_phase.replace(/_/g, ' ')}</div>
              <div className="moon-last-light">
                <span>Last light</span><strong>{clock(o.civil_twilight_end)}</strong>
              </div>
            </div>
          ))}
        </div>
        <p className="insights-fine-print">
          Last light is when the evening glow goes. Times are in your phone's time zone.
        </p>
      </div>}

      {d && <details className="block insights-how">
        <summary>How to read this</summary>
        <p>A sighting is one animal in one photo, so the same animal can be counted more than once, and a camera that fires often counts for more. The weather and moon findings show what the conditions were on busy nights; they do not prove the weather caused it.</p>
      </details>}

      {openClass && (
        <Overlay onClose={closeClass} label={`${openClass} photos`} backLabel="Back to insights">{(close) => (
          <div
            onClick={(e) => e.stopPropagation()}
            className="card ov-panel"
            style={{ padding: 0, maxWidth: 760, width: '100%', margin: 'auto', overflow: 'hidden', display: 'flex', flexDirection: 'column', maxHeight: '90vh' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontWeight: 700, fontSize: 15 }}>{openClass}</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {classImgs ? `${classImgs.length} photo${classImgs.length === 1 ? '' : 's'}` : 'loading…'}
              </span>
              <button
                onClick={close}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text-dim)', borderRadius: 'var(--r-ctl)', padding: '4px 10px', cursor: 'pointer', fontSize: 13 }}
              >
                Close
              </button>
            </div>
            <div style={{ overflowY: 'auto', padding: 12 }}>
              {classErr && <div className="status-panel" role="alert">{classErr}<button className="text-action" onClick={() => openClassImages(openClass)}>Retry</button></div>}
              {!classImgs && !classErr && <div role="status" style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading photos…</div>}
              {classImgs && classImgs.length === 0 && (
                <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>No photos yet.</div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8 }}>
                {classImgs?.map((im, i) => (
                  <div
                    key={im.image_id}
                    className="pressable"
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                    onClick={() => setZoom(i)}
                    style={{ background: 'var(--surface-2)', borderRadius: 'var(--r-ctl)', overflow: 'hidden', cursor: 'pointer' }}
                  >
                    <img src={imageUrl(im.file_url)} loading="lazy" alt={openClass} style={{ width: '100%', height: 104, objectFit: 'cover', display: 'block' }} />
                    <div style={{ padding: '4px 7px', fontSize: 11, color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{im.camera}</span>
                      <span>{new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}</Overlay>
      )}

      {zoom != null && openClass && classImgs && (
        <PhotoLightbox
          photos={classImgs.map((im) => ({ id: im.image_id, file_url: im.file_url, captured_at: im.captured_at, camera: im.camera, label: openClass }))}
          start={zoom}
          backLabel="Back to gallery"
          zIndex={60}
          onClose={() => setZoom(null)}
        />
      )}
    </div>
  )
}
