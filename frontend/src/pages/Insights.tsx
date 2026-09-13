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
  // Bars grow from their baseline once the numbers land, then track the data
  // from there — a refetch slides them to the new value rather than cutting.
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
      if (request === classRequest.current) setClassErr('Could not load photos. Check your connection and retry.')
    }
  }
  function closeClass() {
    classRequest.current++
    setOpenClass(null)
    setClassImgs(null)
  }
  // During a rolling update the old API may still send untyped moon summaries.
  // Typed location summaries can legitimately include camera names like Moon Meadow.
  const observations = d?.correlations.filter(c => c.kind ? c.kind !== 'moon' : !/moon|bright nights|dark nights/i.test(c.statement)) || []

  return (
    <div className="insights-page">
      <div className="insights-header"><div><h1 className="page-title">Insights</h1><p className="page-intro">Get to know the animals on your land.</p></div><Link to="/" className="insights-tonight">Plan tonight <span aria-hidden="true">↗</span></Link></div>
      <WeatherPatterns patterns={pat} scope={patScope} onScope={setPatScope} error={patErr} loading={patLoading} retry={loadPatterns} />
      {err && <div className="status-panel" role="alert">{d ? 'Could not update the calendar and other sightings. Showing the previous results.' : 'Could not load the calendar and other sightings.'}<button className="text-action" onClick={load}>Retry loading insights</button></div>}
      {!d && !err && <p role="status" className="page-intro">Loading the calendar and other sightings…</p>}

      {d && <div className="block insights-calendar">
        <h2 className="sect">Moon & last light this week</h2>
        <p className="page-intro">A calendar to help you plan your evening. It does not predict how many animals you will see.</p>
        <div className="moon-week">
          {d.outlook.map((o) => (
            <div
              key={o.date}
              className="moon-day"
            >
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {dayName(o.date)} {dayNum(o.date)}
              </div>
              <div className="moon-illustration" aria-hidden="true">
                <MoonIcon size={26} weight={o.moon_illum > 65 ? 'fill' : 'regular'} />
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                {Math.round(o.moon_illum)}% lit
              </div>
              <div className="moon-day-phase">{o.moon_phase.replace(/_/g, ' ')}</div>
              <div className="moon-last-light">
                <span>Last light</span><strong>{clock(o.civil_twilight_end)}</strong>
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10, lineHeight: 1.45 }}>
          “Lit” means how much of the moon’s face is sunlit, not how bright it will be outside. Last light is when the remaining evening glow fades. Times follow your device’s time zone.
        </div>
      </div>}

      {d && d.composition && d.composition.length > 0 && (
        <div className="block">
          <h2 className="sect">Who the cameras are seeing</h2>
          {(() => {
            const max = Math.max(...d.composition.map((x) => x.count), 1)
            return d.composition.slice(0, 8).map((x) => (
              <div
                key={x.label}
                className="pressable"
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                onClick={() => openClassImages(x.label)}
                title={`View the ${x.count} ${x.label} photos`}
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, cursor: 'pointer' }}
              >
                <div style={{ width: 100, fontSize: 13 }}>{x.label}</div>
                <div style={{ flex: 1, height: 8, background: 'var(--surface-2)', borderRadius: 'var(--r-chip)', overflow: 'hidden' }}>
                  <div
                    className="bar-x"
                    style={{ width: '100%', height: '100%', background: 'var(--teal)', transform: `scaleX(${grown ? x.count / max : 0})` }}
                  />
                </div>
                <div style={{ width: 28, textAlign: 'right', fontSize: 13, fontVariantNumeric: 'tabular-nums' }}>{x.count}</div>
                <div style={{ width: 88, fontSize: 11, color: 'var(--text-dim)', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={x.top_camera ?? ''}>
                  {x.top_camera}
                </div>
                <span style={{ color: 'var(--text-dim)', fontSize: 15, lineHeight: 1 }}>›</span>
              </div>
            ))
          })()}
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4 }}>
            Recorded group types and the camera with the most sightings. Select a row to view its photos.
          </div>
        </div>
      )}

      {d && <div className="block insights-observations">
        <h2 className="sect">Other things your cameras tell us</h2>
        {observations.length === 0 && <p className="page-intro">More sightings will help reveal the busiest times and places.</p>}
        {observations.map((c, i) => <div className="insights-observation" key={i}>
          <p>{c.statement}</p><span>From {c.sample.toLocaleString()} camera sightings</span>
        </div>)}
        <p className="page-intro">The same animal may appear more than once. Cameras that record more often can account for more sightings.</p>
      </div>}

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
                {classImgs ? `${classImgs.length} sighting${classImgs.length === 1 ? '' : 's'}` : 'loading…'}
              </span>
              <button
                onClick={close}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text-dim)', borderRadius: 'var(--r-ctl)', padding: '4px 10px', cursor: 'pointer', fontSize: 13 }}
              >
                Close
              </button>
            </div>
            <div style={{ overflowY: 'auto', padding: 12 }}>
              {classErr && <div className="status-panel" role="alert">{classErr}<button className="text-action" onClick={() => openClassImages(openClass)}>Retry loading photos</button></div>}
              {!classImgs && !classErr && <div role="status" style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>Loading photos…</div>}
              {classImgs && classImgs.length === 0 && (
                <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>No photos.</div>
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
