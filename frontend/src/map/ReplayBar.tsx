import { PauseIcon } from '@phosphor-icons/react/dist/csr/Pause'
import { PlayIcon } from '@phosphor-icons/react/dist/csr/Play'
import { createPortal } from 'react-dom'
import PhotoLightbox, { type LightboxPhoto } from '../components/PhotoLightbox'
import { t as tr } from '../i18n'
import { SPEEDS, clock, hourMarks, minutesInto, nightLabel } from './activity'
import type { Camera } from './geometry'
import type { useReplay } from './useReplay'

const STEP = 5
const nightCount = (visits: number) => visits ? tr('common.visits', { count: visits }) : tr('replay.nothing')

/**
 * The replay's controls, docked under the map: which night, the timeline from
 * 18:00 to 08:00 with a tick for every visit, play and pause, five minutes either
 * way, and the speed. The timeline is a real slider, so a thumb or a glove drags
 * anywhere along it and the arrow keys step it.
 */
export default function ReplayBar({ replay: r, cameras, photo, onPhoto, onClose }: {
  replay: ReturnType<typeof useReplay>
  cameras: Camera[]
  /** The visit whose photo is open in the viewer, or null. */
  photo: number | null
  onPhoto: (index: number | null) => void
  onClose: () => void
}) {
  const start = r.data ? Date.parse(r.data.start) : null
  const now = start != null ? clock(start + r.t * 60_000) : '18:00'
  const empty = !!r.data && !r.visits.length
  const pct = (m: number) => `${(m / r.total) * 100}%`
  const names = new Map(cameras.map(c => [c.id, c.name]))
  const viewer: LightboxPhoto[] = r.visits.map(v => ({
    id: v.image_id, file_url: `/api/images/${v.image_id}/file`, captured_at: v.at,
    camera: names.get(v.camera_id) ?? '', label: v.group_size > 1 ? `${v.label} (${v.group_size})` : v.label,
  }))
  // Nothing is loading once a load has failed: the error and its Try again say it all.
  const status = r.err || r.nightsErr ? null : !r.data ? (r.nights && !r.nights.length ? tr('replay.noNights') : tr('common.loading'))
    : empty ? tr('replay.noVisits') : tr('replay.soFar', { n: r.soFar, count: r.visits.length })
  const marks = r.data ? hourMarks(r.data.start, r.data.end) : []
  const at = r.nights?.findIndex(n => n.night === r.night) ?? -1
  const shown = r.nights && at >= 0 ? { date: nightLabel(r.nights[at].night, at === 0, r.nights[at].so_far), count: nightCount(r.nights[at].visits) } : null
  return <section className="mode-bar mode-bar--replay" aria-label={tr('replay.label')}>
    <div className="mode-bar-row">
      <label className="replay-night">
        <span className="sr-only">{tr('replay.night')}</span>
        {/* What the closed picker shows, drawn over it so a narrow phone cuts the date
            short and never the count. The real select is on top, and takes the tap. */}
        <span className="replay-night-shown" aria-hidden="true">
          <span className="replay-night-date">{shown ? shown.date : r.nightsErr ? tr('replay.nightsFailed') : tr('replay.loadingNights')}</span>
          {shown && <span className="replay-night-count">&nbsp;· {shown.count}</span>}
        </span>
        <select value={r.night ?? ''} disabled={!r.nights?.length} onChange={e => r.setNight(e.target.value)}>
          {!r.nights && <option value="">{r.nightsErr ? tr('replay.nightsFailed') : tr('replay.loadingNights')}</option>}
          {r.nights?.map((n, i) => <option key={n.night} value={n.night}>{nightLabel(n.night, i === 0, n.so_far)} · {nightCount(n.visits)}</option>)}
        </select>
      </label>
      <button type="button" className="mode-bar-x" aria-label={tr('replay.close')} onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    {r.nightsErr && <p className="map-inline-error" role="alert">{r.nightsErr} <button type="button" className="map-link" onClick={r.reloadNights}>{tr('common.tryAgain')}</button></p>}
    {r.err && <p className="map-inline-error" role="alert">{r.err} <button type="button" className="map-link" onClick={r.reload}>{tr('common.tryAgain')}</button></p>}
    <div className="replay-controls">
      <button type="button" className="map-button replay-step" disabled={!r.data || r.t <= 0} onClick={() => r.setT(r.t - STEP)} aria-label={tr('replay.back5')}>{tr('replay.minus5')}</button>
      <button type="button" className="map-button map-button--primary replay-play" disabled={!r.data || empty} onClick={r.play}
        aria-label={r.playing ? tr('replay.pause') : tr('replay.play')}>
        {r.playing ? <PauseIcon size={26} weight="fill" /> : <PlayIcon size={26} weight="fill" />}
      </button>
      <button type="button" className="map-button replay-step" disabled={!r.data || r.t >= r.total} onClick={() => r.setT(r.t + STEP)} aria-label={tr('replay.fwd5')}>{tr('replay.plus5')}</button>
      <p className="replay-now">
        <strong>{now}</strong>
        {status && <span>{status}</span>}
      </p>
    </div>
    <div className="replay-track">
      <div className="replay-ticks" aria-hidden="true">
        {r.data && r.visits.map((v, i) => {
          const m = minutesInto(v.at, r.data!.start)
          return <i key={i} className={m <= r.t ? 'is-past' : undefined} style={{ left: pct(m) }} />
        })}
      </div>
      <input type="range" min={0} max={r.total} step={1} value={Math.round(r.t)} disabled={!r.data}
        aria-label={tr('replay.time')} aria-valuetext={`${now}, ${status ?? ''}`} onChange={e => r.setT(Number(e.target.value))} />
      <div className="replay-hours" aria-hidden="true">
        {marks.map(x => <span key={x.m} style={{ left: pct(x.m) }}>{x.label}</span>)}
      </div>
    </div>
    <div className="replay-foot">
      <div className="mode-seg replay-speed" role="radiogroup" aria-label={tr('replay.speed')}>
        {SPEEDS.map(s => <button key={s.id} type="button" role="radio" aria-checked={r.speed === s.id} title={tr(s.note)} aria-label={`${s.label}: ${tr(s.note).toLocaleLowerCase()}`} onClick={() => r.setSpeed(s.id)}>{s.label}</button>)}
      </div>
      {/* On a phone on its side only the guess line stays: it is what says the arrow is a guess. */}
      <p className="replay-note">
        <span className="replay-note-speed">{tr(SPEEDS.find(s => s.id === r.speed)?.note ?? 'replay.speed1')}.</span>
        {!!r.data?.links.length && <span className="replay-note-guess"><i className="replay-note-arrow" aria-hidden="true" />{tr('replay.guess')}</span>}
        {r.offMap > 0 && <span className="replay-note-off">{tr('replay.offMap', { count: r.offMap })}</span>}
      </p>
    </div>
    {photo != null && viewer[photo] && createPortal(
      <PhotoLightbox photos={viewer} start={photo} backLabel={tr('replay.backTo')} onClose={() => onPhoto(null)} />, document.body)}
  </section>
}
