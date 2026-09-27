import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getFresh, peek, thumbUrl } from '../api'
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
  // count = visits; photos behind the fold.
  composition: { label: string; count: number; visits?: number; photos?: number; top_camera: string | null }[]
  correlations: { kind?: string; statement: string; strength: number; sample: number }[]
}
type ClassImg = { image_id: string; file_url: string; captured_at: string; camera: string; group_size: number | null }
// A page of a class's photos, newest first; next_before (and _id) ask for the next.
type ClassPage = { items: ClassImg[]; next_before: string | null; next_before_id: string | null }
const dayName =(iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short' })
const dayNum = (iso: string) => new Date(iso + 'T12:00:00').getDate()
const clock = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '–'

// The numbers behind a finding, for the "Show the numbers" fold.
function backing(c: Insights['correlations'][number]) {
  const pct = Math.round(c.strength * 100)
  const visits = `${c.sample.toLocaleString()} visits`
  if (c.kind === 'time') return `${pct}% of ${visits} began in these hours.`
  if (c.kind === 'location') return `${pct}% of ${visits} were at these two cameras.`
  return `From ${visits}.`
}
const plural = (n: number, word: string) => `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

// The findings read every photo on the estate box: slower than a page, but never forever.
const SLOW_MS = 30_000

export default function Insights() {
  // What this session last saw paints at once; the network replaces it (audit K-08).
  const [d, setD] = useState<Insights | null>(() => peek<Insights>('/insights')?.data ?? null)
  const [err, setErr] = useState('')
  const [classErr, setClassErr] = useState('')
  const classRequest = useRef(0)
  const [openClass, setOpenClass] = useState<string | null>(null)
  const [classImgs, setClassImgs] = useState<ClassImg[] | null>(null)
  // Where the next page of the open class starts; null when there is no more.
  const [classNext, setClassNext] = useState<{ before: string; id: string | null } | null>(null)
  const [classMore, setClassMore] = useState(false)
  // Index into classImgs of the photo open in the viewer.
  const [zoom, setZoom] = useState<number | null>(null)
  const [pat, setPat] = useState<Patterns | null>(() => peek<Patterns>('/insights/patterns')?.data ?? null)
  const [patScope, setPatScope] = useState('all')
  const [patErr, setPatErr] = useState('')
  const [patLoading, setPatLoading] = useState(true)
  const patternRequest = useRef(0)
  const [showBars, setShowBars] = useState(false)
  // Bars grow from their baseline once the numbers land, then track the data
  // from there: a refetch slides them to the new value rather than cutting.
  const grown = useReveal(!!d)

  // Leaving the page drops what it was still asking for, so the next tab on a thin
  // link isn't queued behind it (K-08).
  const ctl = useRef<AbortController | null>(null)
  const signal = () => {
    if (!ctl.current || ctl.current.signal.aborted) ctl.current = new AbortController()
    return ctl.current.signal
  }
  useEffect(() => () => ctl.current?.abort(), [])

  function loadPatterns() {
    const request = ++patternRequest.current
    const sig = signal()
    setPatErr('')
    setPatLoading(true)
    getFresh<Patterns>('/insights/patterns', { signal: sig, timeoutMs: SLOW_MS })
      .then(got => { if (request === patternRequest.current) setPat(got.data) })
      .catch(e => { if (request === patternRequest.current && !sig.aborted) setPatErr(e.message) })
      .finally(() => { if (request === patternRequest.current) setPatLoading(false) })
  }
  function load() {
    const sig = signal()
    setErr('')
    getFresh<Insights>('/insights', { signal: sig, timeoutMs: SLOW_MS })
      .then((got) => setD(got.data))
      .catch((e) => { if (!sig.aborted) setErr(e.message) })
    loadPatterns()
  }
  useEffect(load, [])
  useRefetchOnReturn(load, 120_000)

  function classPath(label: string, from: { before: string; id: string | null } | null) {
    const q = new URLSearchParams({ label })
    if (from) {
      q.set('before', from.before)
      if (from.id) q.set('before_id', from.id)
    }
    return '/insights/class?' + q.toString()
  }
  function nextOf(page: ClassPage | ClassImg[]) {
    // An older server sent every photo as one list.
    if (Array.isArray(page) || !page.next_before) return null
    return { before: page.next_before, id: page.next_before_id }
  }
  async function openClassImages(label: string) {
    const request = ++classRequest.current
    setClassErr('')
    setOpenClass(label)
    setClassImgs(null)
    setClassNext(null)
    try {
      const page = await api<ClassPage | ClassImg[]>(classPath(label, null), { signal: signal(), timeoutMs: SLOW_MS })
      if (request !== classRequest.current) return
      setClassImgs(Array.isArray(page) ? page : page.items)
      setClassNext(nextOf(page))
    } catch {
      if (request === classRequest.current) setClassErr('Could not load the photos. Check your connection and try again.')
    }
  }
  async function moreClassImages() {
    if (!openClass || !classNext || classMore) return
    const request = classRequest.current
    setClassMore(true)
    setClassErr('')
    try {
      const page = await api<ClassPage | ClassImg[]>(classPath(openClass, classNext), { signal: signal(), timeoutMs: SLOW_MS })
      if (request !== classRequest.current) return
      const items = Array.isArray(page) ? page : page.items
      setClassImgs((prev) => [...(prev ?? []), ...items])
      setClassNext(nextOf(page))
    } catch {
      if (request === classRequest.current) setClassErr('Could not load older photos. Check your connection and try again.')
    } finally {
      if (request === classRequest.current) setClassMore(false)
    }
  }
  function closeClass() {
    classRequest.current++
    setOpenClass(null)
    setClassImgs(null)
    setClassNext(null)
    setClassMore(false)
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
                title={`See the ${x.label} photos`}
              >
                <div className="insights-class-main">
                  <span className="insights-class-label">{x.label}</span>
                  <span className="insights-class-where">{plural(x.visits ?? x.count, 'visit')}{x.top_camera && `, mostly at ${x.top_camera}`}</span>
                </div>
                {showBars && <div className="insights-class-bar" aria-hidden="true">
                  <div className="bar-x" style={{ transform: `scaleX(${grown ? x.count / maxCount : 0})` }} />
                </div>}
                {showBars && x.photos != null && <span className="insights-class-photos">{plural(x.photos, 'photo')}</span>}
                <span className="insights-class-chevron" aria-hidden="true">›</span>
              </div>
            ))}
          </div>
          <button type="button" className="insights-toggle" aria-pressed={showBars} onClick={() => setShowBars(v => !v)}>
            {showBars ? 'Hide the numbers' : 'Show the numbers'}
          </button>
        </div>
      )}

      {/* After the findings, not before them: the weather is often back first, and the
          findings then pushed it (and the chip under a thumb) 547 px down (audit G-21). */}
      {(d || err) && <WeatherPatterns patterns={pat} scope={patScope} onScope={setPatScope} error={patErr} loading={patLoading} retry={loadPatterns} />}

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
        <p>A visit is one arrival at a camera: photos of the same animal less than half an hour apart count once, so a boar that sat in front of the camera for twenty minutes is one visit, not thirty photos. Only nights a camera was watching are counted; a night it was down or its photos weren't checked yet is left out, not counted as quiet. A weather or moon difference is only called a finding when it beats chance: the same nights shuffled 200 times rarely show one that big. Even then it shows what the conditions were on busy nights, not that the weather caused it.</p>
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
                {classImgs ? `${classImgs.length}${classNext ? '+' : ''} photo${classImgs.length === 1 && !classNext ? '' : 's'}` : 'loading…'}
              </span>
              <button
                onClick={close}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 'var(--r-ctl)', padding: '8px 14px', minHeight: 44, cursor: 'pointer', fontSize: 14 }}
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
                    <img src={thumbUrl(im.image_id)} loading="lazy" alt={openClass} style={{ width: '100%', height: 104, objectFit: 'cover', display: 'block' }} />
                    <div style={{ padding: '4px 7px', fontSize: 11, color: 'var(--text-dim)', display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{im.camera}</span>
                      <span>{new Date(im.captured_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                    </div>
                  </div>
                ))}
              </div>
              {classImgs && classNext && (
                <button type="button" className="insights-more" onClick={() => void moreClassImages()} disabled={classMore} aria-busy={classMore}>
                  {classMore ? 'Loading older photos…' : 'Show older photos'}
                </button>
              )}
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
