import { useEffect, useRef, useState } from 'react'
import { api, getFresh, noAnswer, type Failure } from '../api'
import { baseLabel, type BaseId } from './basemaps'
import type { Camera } from './geometry'
import { download, plan, readSaved, removeSaved, sameBox, SAVABLE, sizeLabel, type Box, type EstateBox, type Progress, type Saved } from './offline'
import { InlineError } from './PlaceSheet'

/** "just now", "3 h ago", "2 days ago". */
export function savedAge(iso: string, now = Date.now()): string {
  const mins = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000))
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

const km = (box: EstateBox) => `${box.box_km[0].toLocaleString()} × ${box.box_km[1].toLocaleString()} km`
const count = (n: number) => n.toLocaleString()

/**
 * Map sheet → Offline: one action that saves the estate on this phone, and a line
 * that says honestly what is saved ("Estate map saved on this phone · 38 MB · 2 days
 * ago"). Anyone can download; an admin sets the box it covers (the view on screen),
 * which is drawn on the map while this sheet is open.
 */
export default function OfflinePanel({ admin, cameras, base, viewBox, onBox, onSaved }: {
  admin: boolean
  cameras: Camera[]
  /** The map type chosen now: saved as it is, when it can be. */
  base: BaseId
  /** The ground the map shows above the sheet, for "Use this view as the estate". */
  viewBox: () => Box | null
  /** The estate's box, to draw while this sheet is open. */
  onBox: (box: Box | null) => void
  onSaved: (saved: Saved | null) => void
}) {
  const [estate, setEstate] = useState<EstateBox | null>(null)
  const [estateErr, setEstateErr] = useState('')
  const [saved, setSaved] = useState<Saved | null | undefined>(undefined)
  const [choice, setChoice] = useState<BaseId>(SAVABLE.includes(base) ? base : 'aerial')
  const [progress, setProgress] = useState<Progress | null>(null)
  const [err, setErr] = useState('')
  const [done, setDone] = useState('')
  const [asking, setAsking] = useState(false)
  const [boxBusy, setBoxBusy] = useState(false)
  const [boxErr, setBoxErr] = useState('')
  const ctl = useRef<AbortController | null>(null)

  useEffect(() => {
    let live = true
    readSaved().then(s => { if (!live) return; setSaved(s); if (s && SAVABLE.includes(s.base)) setChoice(s.base) })
    getFresh<EstateBox>('/estate', { timeoutMs: 20_000 })
      .then(got => { if (live) setEstate(got.data) })
      .catch((e: Failure) => { if (live) setEstateErr(noAnswer(e) ? 'No signal, so the estate’s box didn’t load.' : `Couldn’t load the estate’s box. ${e.message}`) })
    return () => { live = false; ctl.current?.abort() }
  }, [])
  const box = estate?.box ?? saved?.box ?? null
  useEffect(() => { onBox(box); return () => onBox(null) }, [box?.south, box?.west, box?.north, box?.east]) // eslint-disable-line react-hooks/exhaustive-deps

  const busy = !!progress
  const p = box ? plan(box, choice) : null
  async function run() {
    if (!box || busy) return
    const c = new AbortController(); ctl.current = c
    setErr(''); setDone(''); setProgress({ done: 0, total: p?.tiles ?? 0, bytes: 0, stage: 'map' })
    try {
      const s = await download({ base: choice, box, cameras, signal: c.signal, onProgress: setProgress })
      setSaved(s); onSaved(s)
      setDone(s.missing ? 'Saved, with gaps. Download again with better signal to fill them.' : 'Saved. The map works here with no signal.')
    } catch (e) {
      if ((e as Error).name === 'AbortError') setDone('Stopped. What came through is kept; download again to finish it.')
      else setErr((e as Error).message)
    } finally {
      if (ctl.current === c) ctl.current = null
      setProgress(null)
    }
  }
  async function remove() {
    await removeSaved().catch(() => {})
    setSaved(null); onSaved(null); setAsking(false); setDone('Removed from this phone.')
  }
  async function setBox(next: Box | null) {
    setBoxBusy(true); setBoxErr('')
    try {
      const got = next
        ? await api<EstateBox>('/estate/box', { method: 'PUT', body: JSON.stringify(next), timeoutMs: 20_000 })
        : await api<EstateBox>('/estate/box', { method: 'DELETE', timeoutMs: 20_000 })
      setEstate(got)
    } catch (e) {
      setBoxErr(noAnswer(e) ? 'No signal, so the box didn’t change.' : `That didn’t save. ${(e as Error).message}`)
    } finally { setBoxBusy(false) }
  }

  const notes: string[] = []
  if (saved) {
    if (saved.missing) notes.push(`${count(saved.missing)} map ${saved.missing === 1 ? 'square' : 'squares'} didn’t come through. Download again with better signal to fill them.`)
    if (saved.capped) notes.push('It stopped at the size limit, so the closest zoom is only partly saved.')
    if (estate && !sameBox(estate.box, saved.box)) notes.push('The estate’s box has changed since. Download again to match it.')
    if (Date.now() - Date.parse(saved.at) > 7 * 86_400_000) notes.push('The stands, cameras and photos are as they were then. Download again to bring them up to date.')
  }
  const stage = progress?.stage === 'sheets'
    ? `Saving the camera sheets… ${progress.done} of ${progress.total}`
    : progress ? `Saving the map… ${count(progress.done)} of ${count(progress.total)} · ${sizeLabel(progress.bytes)}` : ''

  return <section aria-labelledby="msheet-offline" className="msheet-offline">
    <h3 id="msheet-offline">Offline</h3>
    <p className={`msheet-status${saved ? ' msheet-status--saved' : ''}`} role="status">
      {saved === undefined ? 'Checking this phone…'
        : saved ? `Estate map saved on this phone · ${sizeLabel(saved.bytes)} · ${savedAge(saved.at)}`
          : 'Not saved on this phone. Save it before you head out, and the map works with no signal.'}
    </p>
    {saved && <p className="msheet-note">{baseLabel(saved.base)}, with the stands, cameras, bedding and each camera’s latest photos.</p>}
    {notes.map(n => <p key={n} className="msheet-note msheet-note--warn">{n}</p>)}

    {/* Two savable map types: say which. Esri's world imagery can't be kept. */}
    <div className="msheet-segments msheet-segments--two" role="radiogroup" aria-label="Map type to save">
      {SAVABLE.map(b => <button key={b} type="button" role="radio" aria-checked={choice === b} disabled={busy} onClick={() => setChoice(b)}>{baseLabel(b)}</button>)}
    </div>
    {base === 'world' && <p className="msheet-note">{baseLabel('world')} can’t be saved: Esri doesn’t allow copies for use with no signal.</p>}

    {busy ? <div className="msheet-progress" role="status">
      <span>{stage}</span>
      <button type="button" className="map-button" onClick={() => ctl.current?.abort()}>Stop</button>
    </div> : <button type="button" className="map-button map-button--primary map-button--big" disabled={!box} onClick={run}>
      {saved ? 'Download again' : 'Download the estate for offline'}
    </button>}
    {p && !busy && <details className="msheet-numbers">
      <summary>About {sizeLabel(p.bytes)}. Best on Wi-Fi.</summary>
      <p>{count(p.tiles)} map squares, zoom {p.minZoom} to {p.maxZoom}{estate ? `, over ${km(estate)}` : ''}. Squares already saved aren’t downloaded again.</p>
    </details>}
    {!box && estateErr && <p className="msheet-note msheet-note--warn">{estateErr} The download needs signal.</p>}
    {err && <InlineError text={err} />}
    {done && <p className="msheet-note" role="status">{done}</p>}
    {saved && !busy && (asking
      ? <div className="map-confirm" role="group" aria-label="Remove the saved map">
          <p>Remove the saved map from this phone? It needs signal to download again.</p>
          <div className="map-actions"><button type="button" className="map-button" onClick={remove}>Remove</button><button type="button" className="map-button" onClick={() => setAsking(false)}>Keep</button></div>
        </div>
      : <button type="button" className="map-link" onClick={() => setAsking(true)}>Remove from this phone</button>)}

    {admin && estate && <div className="msheet-box">
      <p className="msheet-note">
        The estate’s box: {km(estate)}, {estate.box_set ? 'set by an admin' : 'drawn round the stands, cameras and bedding'}. Everyone’s download covers it; it’s the dashed frame on the map.
      </p>
      <div className="map-actions">
        <button type="button" className="map-button" disabled={boxBusy} onClick={() => { const v = viewBox(); if (v) setBox(v) }}>Use this view as the estate</button>
        {estate.box_set && <button type="button" className="map-button" disabled={boxBusy} onClick={() => setBox(null)}>Round everything placed</button>}
      </div>
      {boxErr && <InlineError text={boxErr} />}
    </div>}
  </section>
}
