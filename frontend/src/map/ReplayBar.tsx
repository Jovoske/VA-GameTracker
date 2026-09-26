import { PauseIcon } from '@phosphor-icons/react/dist/csr/Pause'
import { PlayIcon } from '@phosphor-icons/react/dist/csr/Play'
import { createPortal } from 'react-dom'
import PhotoLightbox, { type LightboxPhoto } from '../components/PhotoLightbox'
import { SPEEDS, clock, minutesInto, nightLabel } from './activity'
import type { Camera } from './geometry'
import type { useReplay } from './useReplay'

const STEP = 5
// Hour marks under the timeline, in minutes after 18:00.
const MARKS = [0, 180, 360, 540, 720, 840]
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

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
  const status = r.err ? null : !r.data ? (r.nights && !r.nights.length ? 'No nights yet' : 'Loading…')
    : empty ? 'No visits' : `${r.soFar} of ${plural(r.visits.length, 'visit')}`
  return <section className="mode-bar mode-bar--replay" aria-label="Replay a night">
    <div className="mode-bar-row">
      <label className="replay-night">
        <span className="sr-only">Night</span>
        <select value={r.night ?? ''} disabled={!r.nights?.length} onChange={e => r.setNight(e.target.value)}>
          {!r.nights && <option value="">Loading nights…</option>}
          {r.nights?.map((n, i) => <option key={n.night} value={n.night}>{nightLabel(n.night, i === 0)} · {n.visits ? plural(n.visits, 'visit') : 'nothing'}</option>)}
        </select>
      </label>
      <button type="button" className="mode-bar-x" aria-label="Close replay, back to the camera photos" onClick={onClose}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
      </button>
    </div>
    {r.nightsErr && <p className="map-inline-error" role="alert">{r.nightsErr} <button type="button" className="map-link" onClick={r.reloadNights}>Try again</button></p>}
    {r.err && <p className="map-inline-error" role="alert">{r.err} <button type="button" className="map-link" onClick={r.reload}>Try again</button></p>}
    <div className="replay-controls">
      <button type="button" className="map-button replay-step" disabled={!r.data || r.t <= 0} onClick={() => r.setT(r.t - STEP)} aria-label="Back 5 minutes">−5 min</button>
      <button type="button" className="map-button map-button--primary replay-play" disabled={!r.data || empty} onClick={r.play}
        aria-label={r.playing ? 'Pause' : 'Play'}>
        {r.playing ? <PauseIcon size={26} weight="fill" /> : <PlayIcon size={26} weight="fill" />}
      </button>
      <button type="button" className="map-button replay-step" disabled={!r.data || r.t >= r.total} onClick={() => r.setT(r.t + STEP)} aria-label="Forward 5 minutes">+5 min</button>
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
        aria-label="Time of night" aria-valuetext={`${now}, ${status ?? ''}`} onChange={e => r.setT(Number(e.target.value))} />
      <div className="replay-hours" aria-hidden="true">
        {MARKS.map(m => <span key={m} style={{ left: pct(m) }}>{start != null ? clock(start + m * 60_000).slice(0, 2) : ''}</span>)}
      </div>
    </div>
    <div className="replay-foot">
      <div className="mode-seg replay-speed" role="radiogroup" aria-label="Speed">
        {SPEEDS.map(s => <button key={s.id} type="button" role="radio" aria-checked={r.speed === s.id} title={s.note} aria-label={`${s.label}: ${s.note.toLowerCase()}`} onClick={() => r.setSpeed(s.id)}>{s.label}</button>)}
      </div>
      <p className="replay-note">
        <span>{SPEEDS.find(s => s.id === r.speed)?.note}.</span>
        {!!r.data?.links.length && <span><i className="replay-note-arrow" aria-hidden="true" />Likely went this way: a guess, from the same animal at the next camera within 3 h.</span>}
        {r.offMap > 0 && <span>{plural(r.offMap, 'visit')} at cameras not on the map.</span>}
      </p>
    </div>
    {photo != null && viewer[photo] && createPortal(
      <PhotoLightbox photos={viewer} start={photo} backLabel="Back to the replay" onClose={() => onPhoto(null)} />, document.body)}
  </section>
}
