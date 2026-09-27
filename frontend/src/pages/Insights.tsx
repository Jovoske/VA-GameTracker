import { MoonIcon } from '@phosphor-icons/react/dist/csr/Moon'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getFresh, peek, thumbUrl } from '../api'
import Overlay from '../components/Overlay'
import PhotoLightbox from '../components/PhotoLightbox'
import WeatherPatterns, { type Patterns } from '../components/WeatherPatterns'
import { useRefetchOnReturn, useReveal } from '../hooks'
import { fmtDate, fmtNumber, fmtTime, fmtWeekday, t, tOr } from '../i18n'
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
const dayName = (iso: string) => fmtWeekday(iso + 'T12:00:00')
const dayNum = (iso: string) => new Date(iso + 'T12:00:00').getDate()
const clock = (iso: string | null) => (iso ? fmtTime(iso) : '–')
/** "Full Moon" as the server names the phase, in the language on screen. */
const moonWords = (phase: string) => tOr(`moon.${phase.toLowerCase().replace(/[\s_]+/g, '_')}`, phase.replace(/_/g, ' '))

// The numbers behind a finding, for the "Show the numbers" fold.
function backing(c: Insights['correlations'][number]) {
  const pct = Math.round(c.strength * 100)
  const visits = t('insights.visitsN', { count: c.sample, n: fmtNumber(c.sample) })
  if (c.kind === 'time') return t('insights.backTime', { pct, visits })
  if (c.kind === 'location') return t('insights.backPlace', { pct, visits })
  return t('insights.backFrom', { visits })
}

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
      if (request === classRequest.current) setClassErr(t('insights.couldntPhotos'))
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
      if (request === classRequest.current) setClassErr(t('insights.couldntOlder'))
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
      <div className="insights-header"><div><h1 className="page-title">{t('nav.insights')}</h1><p className="page-intro">{t('insights.intro')}</p></div><Link to="/" className="insights-tonight">{t('insights.planTonight')} <span aria-hidden="true">↗</span></Link></div>
      {err && <div className="status-panel" role="alert">{d ? t('insights.couldntRefresh') : t('insights.couldntLoad')}<button className="text-action" onClick={load}>{t('common.retry')}</button></div>}
      {!d && !err && <p role="status" className="page-intro">{t('insights.reading')}</p>}

      {d && <div className="block insights-findings-block">
        <h2 className="sect">{t('insights.seen')}</h2>
        {findings.length === 0 && <p className="page-intro">{t('insights.notEnough')}</p>}
        {findings.length > 0 && <>
          <ul className="insights-findings">
            {findings.map((c, i) => <li key={i}>{c.statement}</li>)}
          </ul>
          <details className="insights-numbers">
            <summary>{t('weather.showNumbers')}</summary>
            <ul>{findings.map((c, i) => <li key={i}><span>{c.statement}</span> {backing(c)}</li>)}</ul>
          </details>
        </>}
      </div>}

      {d && d.composition && d.composition.length > 0 && (
        <div className="block">
          <h2 className="sect">{t('insights.who')}</h2>
          <p className="page-intro">{t('insights.tapRow')}</p>
          <div className="insights-classes">
            {d.composition.slice(0, 8).map((x) => (
              <div
                key={x.label}
                className="pressable insights-class"
                role="button"
                tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click() } }}
                onClick={() => openClassImages(x.label)}
                title={t('insights.seePhotos', { label: x.label })}
              >
                <div className="insights-class-main">
                  <span className="insights-class-label">{x.label}</span>
                  <span className="insights-class-where">{x.top_camera
                    ? t('insights.visitsMostly', { count: x.visits ?? x.count, n: fmtNumber(x.visits ?? x.count), camera: x.top_camera })
                    : t('insights.visitsN', { count: x.visits ?? x.count, n: fmtNumber(x.visits ?? x.count) })}</span>
                </div>
                {showBars && <div className="insights-class-bar" aria-hidden="true">
                  <div className="bar-x" style={{ transform: `scaleX(${grown ? x.count / maxCount : 0})` }} />
                </div>}
                {showBars && x.photos != null && <span className="insights-class-photos">{t('insights.photosN', { count: x.photos, n: fmtNumber(x.photos) })}</span>}
                <span className="insights-class-chevron" aria-hidden="true">›</span>
              </div>
            ))}
          </div>
          <button type="button" className="insights-toggle" aria-pressed={showBars} onClick={() => setShowBars(v => !v)}>
            {showBars ? t('insights.hideNumbers') : t('weather.showNumbers')}
          </button>
        </div>
      )}

      {/* After the findings, not before them: the weather is often back first, and the
          findings then pushed it (and the chip under a thumb) 547 px down (audit G-21). */}
      {(d || err) && <WeatherPatterns patterns={pat} scope={patScope} onScope={setPatScope} error={patErr} loading={patLoading} retry={loadPatterns} />}

      {d && <div className="block insights-calendar">
        <h2 className="sect">{t('insights.moonWeek')}</h2>
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
                {t('insights.lit', { pct: Math.round(o.moon_illum) })}
              </div>
              <div className="moon-day-phase">{moonWords(o.moon_phase)}</div>
              <div className="moon-last-light">
                <span>{t('insights.lastLight')}</span><strong>{clock(o.civil_twilight_end)}</strong>
              </div>
            </div>
          ))}
        </div>
        <p className="insights-fine-print">
          {t('insights.lastLightNote')}
        </p>
      </div>}

      {d && <details className="block insights-how">
        <summary>{t('insights.howToRead')}</summary>
        <p>{t('insights.howToReadText')}</p>
      </details>}

      {openClass && (
        <Overlay onClose={closeClass} label={t('insights.classPhotos', { label: openClass })} backLabel={t('insights.back')}>{(close) => (
          <div
            onClick={(e) => e.stopPropagation()}
            className="card ov-panel"
            style={{ padding: 0, maxWidth: 760, width: '100%', margin: 'auto', overflow: 'hidden', display: 'flex', flexDirection: 'column', maxHeight: '90vh' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
              <span style={{ fontWeight: 700, fontSize: 15 }}>{openClass}</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {classImgs ? t('insights.classCount', { count: classImgs.length === 1 && !classNext ? 1 : 2, n: `${classImgs.length}${classNext ? '+' : ''}` }) : t('insights.loadingLower')}
              </span>
              <button
                onClick={close}
                style={{ marginLeft: 'auto', background: 'none', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 'var(--r-ctl)', padding: '8px 14px', minHeight: 44, cursor: 'pointer', fontSize: 14 }}
              >
                {t('common.close')}
              </button>
            </div>
            <div style={{ overflowY: 'auto', padding: 12 }}>
              {classErr && <div className="status-panel" role="alert">{classErr}<button className="text-action" onClick={() => openClassImages(openClass)}>{t('common.retry')}</button></div>}
              {!classImgs && !classErr && <div role="status" style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>{t('photos.loading')}</div>}
              {classImgs && classImgs.length === 0 && (
                <div style={{ color: 'var(--text-dim)', fontSize: 13, padding: 8 }}>{t('cameras.noPhotos')}</div>
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
                      <span>{fmtDate(im.captured_at, { month: 'short', day: 'numeric' })}</span>
                    </div>
                  </div>
                ))}
              </div>
              {classImgs && classNext && (
                <button type="button" className="insights-more" onClick={() => void moreClassImages()} disabled={classMore} aria-busy={classMore}>
                  {classMore ? t('lb.loadingOlder') : t('photos.older')}
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
          backLabel={t('insights.backGallery')}
          zIndex={60}
          onClose={() => setZoom(null)}
        />
      )}
    </div>
  )
}
