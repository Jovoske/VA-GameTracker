import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { useEffect, useRef, useState } from 'react'
import { api, imageUrl } from '../api'
import Overlay from '../components/Overlay'
import { useRefetchOnReturn, useReveal } from '../hooks'

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
  correlations: { statement: string; strength: number; sample: number }[]
}
type ClassImg = { image_id: string; file_url: string; captured_at: string; camera: string; group_size: number | null }
type Driver = {
  factor: string
  key?: string
  statement: string
  effect_pct: number
  sample_nights: number
  confidence: number
  buckets: { label: string; rate: number; days?: number; min?: number; max?: number }[]
  correlation: number
}
type PScope = {
  key: string
  label: string
  drivers: Driver[]
  active_nights: number
  total_nights: number
  avg_per_night: number
  sightings: number
}
type Patterns = { scopes: PScope[]; nights: number; range?: [string, string] }

function formatRange(key: string, min: number, max: number) {
  const divisor = key === 'darkness' ? 60 : 1
  const unit = key === 'darkness' ? ' h' : ['moon_illum', 'cloud'].includes(key) ? '%' : key === 'temp' ? ' °C' : key === 'wind' ? ' km/h' : key === 'rain' ? ' mm' : key.startsWith('pressure') ? ' hPa' : ''
  return (min / divisor).toFixed(1) + '–' + (max / divisor).toFixed(1) + unit
}

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
  const [zoom, setZoom] = useState<string | null>(null)
  const [pat, setPat] = useState<Patterns | null>(null)
  const [patScope, setPatScope] = useState('all')
  // Bars grow from their baseline once the numbers land, then track the data
  // from there — a refetch slides them to the new value rather than cutting.
  const grown = useReveal(!!d)

  function load() {
    setErr('')
    api<Insights>('/insights').then(setD).catch((e) => setErr(e.message))
    api<Patterns>('/insights/patterns').then(setPat).catch(() => {})
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

  if (err && !d) return <div className="status-panel" role="alert">Could not load insights: {err}<button className="text-action" onClick={load}>Retry loading insights</button></div>
  if (!d) return <div role="status" style={{ color: 'var(--text-dim)' }}>Loading activity insights…</div>

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <h1 className="page-title">Insights</h1>
      <p className="page-intro">Explore recorded animal activity, weather associations, and light conditions for the coming week.</p>
      {err && <div className="status-panel" role="alert">Could not refresh insights. Showing the previous results.<button className="text-action" onClick={load}>Retry</button></div>}

      <div className="block">
        <h2 className="sect">The next seven nights</h2>
        <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
          {d.outlook.map((o) => (
            <div
              key={o.date}
              title={`${o.moon_phase} · last light ${clock(o.civil_twilight_end)}`}
              style={{
                flex: '1 0 68px',
                textAlign: 'center',
                padding: '8px 4px',
                borderRadius: 'var(--r-ctl)',
                background: 'var(--surface-2)',
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {dayName(o.date)} {dayNum(o.date)}
              </div>
              <div style={{ margin: '5px 0 3px', color: 'var(--text-dim)', display: 'flex', justifyContent: 'center' }}>
                <MoonIcon size={15} />
              </div>
              <div style={{ fontSize: 12, fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                {Math.round(o.moon_illum)}%
              </div>
              <div style={{ fontSize: 9, color: 'var(--text-dim)', marginTop: 3 }}>
                {clock(o.civil_twilight_end)}
              </div>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 10, lineHeight: 1.45 }}>
          Each day shows the illuminated percentage of the moon and the end of civil twilight in your device's local time. For tonight's animal-activity forecast, open Tonight.
        </div>
      </div>

      {d.composition && d.composition.length > 0 && (
        <div className="block">
          <h2 className="sect">Animal groups by camera</h2>
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

      {pat && pat.scopes.length > 0 && (() => {
        const sc = pat.scopes.find((s) => s.key === patScope) || pat.scopes[0]
        return (
          <div className="block">
            <h2 className="sect">Weather and moon associations</h2>
            <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
              {pat.scopes.map((s) => (
                <button
                  key={s.key}
                  onClick={() => setPatScope(s.key)}
                  style={{
                    fontSize: 12, padding: '4px 10px', borderRadius: 'var(--r-ctl)', cursor: 'pointer',
                    border: '1px solid var(--border)',
                    background: s.key === sc.key ? 'var(--surface-2)' : 'transparent',
                    color: s.key === sc.key ? 'var(--text)' : 'var(--text-dim)',
                    fontWeight: s.key === sc.key ? 600 : 400,
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            {sc.drivers.length === 0 && (
              <div style={{ fontSize: 13, color: 'var(--text-dim)' }}>No clear weather or moon driver yet. It needs more nights.</div>
            )}
            <p className="page-intro">Exploratory comparisons of recorded detections. Each factor is compared separately; season, camera uptime, repeated triggers, and other conditions are not controlled for.</p>
            {sc.drivers.map((dr, i) => {
              const key = dr.key || (dr.factor === 'Moonlight' ? 'moon_illum' : dr.factor === 'Dark hours' ? 'darkness' : '')
              const title = key === 'moon_illum' ? 'Moon illumination' : key === 'darkness' ? 'Night duration' : dr.factor
              const definition = key === 'moon_illum'
                ? 'Illuminated fraction of the moon. This does not measure light at ground level or account for clouds or the moon being above the horizon.'
                : key === 'darkness' ? 'Hours outside daylight, calculated from sunrise and sunset. Shorter nights have fewer hours of darkness; cloud cover is a separate measurement.'
                : key === 'cloud' ? 'Average cloud cover during the overnight weather window.' : 'Lower and higher refer to the bottom and top thirds of this measurement in the recorded sample.'
              return <section key={i} className="pattern-comparison">
                <h3>{title}</h3><p>{definition}</p>
                <table><caption>Average detections per recording day</caption><thead><tr><th>Measurement group</th><th>Detections / day</th><th>Days</th></tr></thead><tbody>{dr.buckets.map(bucket => <tr key={bucket.label}><th>{bucket.label === 'low' ? 'Lower third' : bucket.label === 'high' ? 'Higher third' : 'Middle third'}{bucket.min != null && bucket.max != null && <small>{formatRange(key, bucket.min, bucket.max)}</small>}</th><td>{bucket.rate.toFixed(1)}</td><td>{bucket.days ?? '—'}</td></tr>)}</tbody></table>
                <p>{dr.sample_nights} recording days compared. This is an association in this sample, not evidence that the condition caused more activity.</p>
              </section>
            })}
            <p className="page-intro">{sc.label}: {sc.sightings} detections across {sc.total_nights} recording days. Each day runs 06:00–06:00 in estate time and includes daytime detections; weather is summarized for the overnight window. Counts are not unique animals or adjusted for camera uptime.</p>
          </div>
        )
      })()}

      <div className="block">
        <h2 className="sect">Patterns</h2>
        {d.correlations.length === 0 && (
          <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>Not enough data yet to call patterns.</div>
        )}
        {d.correlations.map((c, i) => (
          <div
            key={i}
            style={{
              marginBottom: 12,
              paddingBottom: 12,
              borderBottom: i < d.correlations.length - 1 ? '1px solid var(--border)' : 'none',
            }}
          >
            <div style={{ fontSize: 14, lineHeight: 1.4 }}>{c.statement}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
              <div style={{ flex: 1, maxWidth: 140, height: 4, background: 'var(--surface-2)', borderRadius: 'var(--r-chip)', overflow: 'hidden' }}>
                <div className="bar-x" style={{ width: '100%', height: '100%', background: 'var(--teal)', transform: `scaleX(${grown ? Math.min(1, c.strength) : 0})` }} />
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>based on {c.sample} sightings</span>
            </div>
          </div>
        ))}
      </div>

      <div style={{ color: 'var(--text-dim)', fontSize: 11, textAlign: 'center' }}>
        These patterns describe recorded activity, not proven causes. More camera nights can change the results.
      </div>

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
                {classImgs?.map((im) => (
                  <div
                    key={im.image_id}
                    className="pressable"
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                    onClick={() => setZoom(imageUrl(im.file_url))}
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

      {zoom && (
        <Overlay
          label="Photo details"
          backLabel="Back to gallery"
          onClose={() => setZoom(null)}
          backdrop="rgba(0, 0, 0, 0.92)"
          zIndex={60}
          style={{ alignItems: 'center', justifyContent: 'center' }}
        >
          {(_close) => (
            <img className="ov-panel" src={zoom} alt={`${openClass} trail-camera photo`} style={{ maxWidth: '94vw', maxHeight: '75dvh', borderRadius: 'var(--r-ctl)' }} />
          )}
        </Overlay>
      )}
    </div>
  )
}
