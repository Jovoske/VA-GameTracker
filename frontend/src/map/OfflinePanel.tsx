import { useEffect, useState } from 'react'
import { api, getFresh, noAnswer, type Failure } from '../api'
import { baseLabel, type BaseId } from './basemaps'
import type { Camera } from './geometry'
import { plan, readSaved, removeSaved, sameBox, SAVABLE, sizeLabel, startDownload, stopDownload, storedCount, useDownload, type Box, type EstateBox, type Progress, type Saved } from './offline'
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

/** Cameras whose position is too far off to be on the estate, and what to do. */
function farWords(far: NonNullable<EstateBox['cameras_left_out']>): string {
  if (far.length === 1) return `${far[0].name} shows ${far[0].km} km from the estate, so it is left out of the box and the hill shape. If it is out there, move it on the map.`
  return `${far.map(c => `${c.name} (${c.km} km)`).join(', ')} show too far from the estate, so they are left out of the box and the hill shape. If they are out there, move them on the map.`
}

/** How far a download has got, in words: for this sheet and the pill on the map. */
export function progressWords(p: Progress): string {
  return p.stage === 'sheets'
    ? `Saving the camera sheets… ${p.done} of ${p.total}`
    : `Saving the map… ${count(p.done)} of ${count(p.total)} · ${sizeLabel(p.bytes)}`
}

/**
 * Map sheet → Offline: one action that saves the estate on this phone, and a line
 * that says honestly what is saved ("Estate map saved on this phone · 38 MB · 2 days
 * ago", or "Part of the estate saved" when a download stopped part way). Anyone can
 * download; an admin sets the box it covers (the view on screen), which is drawn on
 * the map while this sheet is open. The download itself runs in offline.ts: closing
 * this sheet leaves it running, and the map shows how far it has got.
 */
export default function OfflinePanel({ admin, cameras, base, viewBox, onBox }: {
  admin: boolean
  cameras: Camera[]
  /** The map type chosen now: saved as it is, when it can be. */
  base: BaseId
  /** The ground the map shows above the sheet, for "Use this view as the estate". */
  viewBox: () => Box | null
  /** The estate's box, to draw while this sheet is open. */
  onBox: (box: Box | null) => void
}) {
  const job = useDownload()
  const [estate, setEstate] = useState<EstateBox | null>(null)
  const [estateErr, setEstateErr] = useState('')
  const [saved, setSaved] = useState<Saved | null | undefined>(undefined)
  // Things in the store with no note of them: a download killed before its first note.
  const [leftovers, setLeftovers] = useState(0)
  const [choice, setChoice] = useState<BaseId>(SAVABLE.includes(base) ? base : 'aerial')
  // Set once the map type to save follows what is saved, or the hunter picked one.
  const [chosen, setChosen] = useState(false)
  const [asking, setAsking] = useState(false)
  const [removed, setRemoved] = useState(false)
  const [boxBusy, setBoxBusy] = useState(false)
  const [boxErr, setBoxErr] = useState('')

  useEffect(() => {
    let live = true
    getFresh<EstateBox>('/estate', { timeoutMs: 20_000 })
      .then(got => { if (live) setEstate(got.data) })
      .catch((e: Failure) => { if (live) setEstateErr(noAnswer(e) ? 'No signal, so the estate’s box didn’t load.' : `Couldn’t load the estate’s box. ${e.message}`) })
    return () => { live = false }
  }, [])
  // What is on the phone: read again whenever a download writes its note or ends.
  useEffect(() => {
    let live = true
    Promise.all([readSaved(), storedCount()]).then(([s, n]) => {
      if (!live) return
      setSaved(s); setLeftovers(s ? 0 : n)
      if (s && SAVABLE.includes(s.base) && !chosen) { setChoice(s.base); setChosen(true) }
    })
    return () => { live = false }
  }, [job.version]) // eslint-disable-line react-hooks/exhaustive-deps
  const box = estate?.box ?? saved?.box ?? null
  useEffect(() => { onBox(box); return () => onBox(null) }, [box?.south, box?.west, box?.north, box?.east]) // eslint-disable-line react-hooks/exhaustive-deps

  const progress = job.progress
  const busy = !!progress
  const p = box ? plan(box, choice) : null
  function run() {
    if (!box || busy) return
    setRemoved(false)
    startDownload({ base: choice, box, cameras })
  }
  async function remove() {
    await removeSaved().catch(() => {})
    setAsking(false); setRemoved(true)
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

  const part = !!saved?.partial
  const notes: string[] = []
  if (saved && !busy) {
    if (part) notes.push(saved.tiles + saved.missing >= (saved.planned ?? Infinity)
      ? 'The map is saved; the camera sheets and their photos aren’t yet. Download again to finish it.'
      : `${count(saved.tiles)} of ${count(saved.planned ?? saved.tiles)} map squares so far. Download again to finish it.`)
    else if (saved.missing) notes.push(`${count(saved.missing)} map ${saved.missing === 1 ? 'square' : 'squares'} didn’t come through. Download again with better signal to fill them.`)
    if (saved.capped) notes.push('It stopped at the size limit, so the closest zoom is only partly saved.')
    if (estate && !sameBox(estate.box, saved.box)) notes.push('The estate’s box has changed since. Download again to match it.')
    if (!part && Date.now() - Date.parse(saved.at) > 7 * 86_400_000) notes.push('The stands, cameras and photos are as they were then. Download again to bring them up to date.')
  }
  const status = saved === undefined ? 'Checking this phone…'
    : saved ? `${part ? 'Part of the estate saved on this phone' : 'Estate map saved on this phone'} · ${sizeLabel(saved.bytes)} · ${savedAge(saved.at)}`
      : leftovers ? 'Part of a download is on this phone. Download again to finish it, or remove it.'
        : 'Not saved on this phone. Save it before you head out, and the map works with no signal.'
  const outcome = removed ? { ok: true, text: 'Removed from this phone.' } : job.outcome
  const farOff = estate?.cameras_left_out ?? []

  return <section aria-labelledby="msheet-offline" className="msheet-offline">
    <h3 id="msheet-offline">Offline</h3>
    <p className={`msheet-status${saved && !part ? ' msheet-status--saved' : ''}`} role="status">{status}</p>
    {saved && !part && <p className="msheet-note">{baseLabel(saved.base)}, with the stands, cameras, bedding and each camera’s latest photos.</p>}
    {notes.map(n => <p key={n} className="msheet-note msheet-note--warn">{n}</p>)}

    {/* Two savable map types: say which. Esri's world imagery can't be kept. */}
    <div className="msheet-segments msheet-segments--two" role="radiogroup" aria-label="Map type to save">
      {SAVABLE.map(b => <button key={b} type="button" role="radio" aria-checked={(busy ? job.base : choice) === b} disabled={busy} onClick={() => { setChoice(b); setChosen(true) }}>{baseLabel(b)}</button>)}
    </div>
    {base === 'world' && <p className="msheet-note">{baseLabel('world')} can’t be saved: Esri doesn’t allow copies for use with no signal.</p>}

    {busy ? <div className="msheet-progress" role="status">
      <span>{progressWords(progress)}</span>
      <button type="button" className="map-button" onClick={stopDownload}>Stop</button>
    </div> : <button type="button" className="map-button map-button--primary map-button--big" disabled={!box} onClick={run}>
      {part && saved?.base === choice ? 'Finish the download' : saved || leftovers ? 'Download again' : 'Download the estate for offline'}
    </button>}
    {busy && <p className="msheet-note">It carries on with this sheet closed. The map shows how far it has got.</p>}
    {p && !busy && <details className="msheet-numbers">
      <summary>About {sizeLabel(p.bytes)}. Best on Wi-Fi.</summary>
      <p>{count(p.tiles)} map squares, zoom {p.minZoom} to {p.maxZoom}{estate ? `, over ${km(estate)}` : ''}. Squares already saved aren’t downloaded again.</p>
    </details>}
    {!box && estateErr && <p className="msheet-note msheet-note--warn">{estateErr} The download needs signal.</p>}
    {outcome && !busy && (outcome.ok ? <p className="msheet-note" role="status">{outcome.text}</p> : <InlineError text={outcome.text} />)}
    {(saved || leftovers > 0) && !busy && (asking
      ? <div className="map-confirm" role="group" aria-label="Remove the saved map">
          <p>Remove the saved map from this phone? It needs signal to download again.</p>
          <div className="map-actions"><button type="button" className="map-button" onClick={remove}>Remove</button><button type="button" className="map-button" onClick={() => setAsking(false)}>Keep</button></div>
        </div>
      : <button type="button" className="map-link" onClick={() => setAsking(true)}>Remove from this phone</button>)}

    {admin && estate && <div className="msheet-box">
      <p className="msheet-note">
        The estate’s box: {km(estate)}, {estate.box_set ? 'set by an admin' : 'drawn round the stands, cameras and bedding'}. Everyone’s download covers it; it’s the dashed frame on the map.
      </p>
      {farOff.length > 0 && <p className="msheet-note msheet-note--warn">{farWords(farOff)}</p>}
      <div className="map-actions">
        <button type="button" className="map-button" disabled={boxBusy} onClick={() => { const v = viewBox(); if (v) setBox(v) }}>Use this view as the estate</button>
        {estate.box_set && <button type="button" className="map-button" disabled={boxBusy} onClick={() => setBox(null)}>Round everything placed</button>}
      </div>
      {boxErr && <InlineError text={boxErr} />}
    </div>}
  </section>
}
