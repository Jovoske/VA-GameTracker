import { useEffect, useState } from 'react'
import { api, getFresh, noAnswer, type Failure } from '../api'
import { fmtNumber, t } from '../i18n'
import { baseLabel, type BaseId } from './basemaps'
import type { Camera } from './geometry'
import { plan, readSaved, removeSaved, sameBox, SAVABLE, sizeLabel, startDownload, stopDownload, storedCount, useDownload, type Box, type EstateBox, type Progress, type Saved } from './offline'
import { InlineError } from './PlaceSheet'

/** "just now", "3 h ago", "2 days ago". */
export function savedAge(iso: string, now = Date.now()): string {
  const mins = Math.max(0, Math.round((now - Date.parse(iso)) / 60_000))
  if (mins < 2) return t('time.justNow')
  if (mins < 60) return t('time.minAgo', { n: fmtNumber(mins) })
  const hours = Math.round(mins / 60)
  if (hours < 24) return t('time.hAgo', { n: fmtNumber(hours) })
  const days = Math.round(hours / 24)
  return t('offline.daysAgo', { count: days, n: fmtNumber(days) })
}

const km = (box: EstateBox) => `${fmtNumber(box.box_km[0])} × ${fmtNumber(box.box_km[1])} km`
const count = (n: number) => fmtNumber(n)

/** Cameras whose position is too far off to be on the estate, and what to do. */
function farWords(far: NonNullable<EstateBox['cameras_left_out']>): string {
  if (far.length === 1) return t('offline.farOne', { name: far[0].name, km: fmtNumber(far[0].km) })
  return t('offline.farMany', { names: far.map(c => `${c.name} (${fmtNumber(c.km)} km)`).join(', ') })
}

/** How far a download has got, in words: for this sheet and the pill on the map. */
export function progressWords(p: Progress): string {
  return p.stage === 'sheets'
    ? t('offline.savingSheets', { n: p.done, of: p.total })
    : t('offline.savingMap', { n: count(p.done), of: count(p.total), size: sizeLabel(p.bytes) })
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
      .catch((e: Failure) => { if (live) setEstateErr(noAnswer(e) ? t('offline.boxNoSignal') : t('offline.boxCouldnt', { why: e.message })) })
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
      setBoxErr(noAnswer(e) ? t('offline.boxNotChanged') : t('common.notSaved', { why: (e as Error).message }))
    } finally { setBoxBusy(false) }
  }

  const part = !!saved?.partial
  const notes: string[] = []
  if (saved && !busy) {
    if (part) notes.push(saved.tiles + saved.missing >= (saved.planned ?? Infinity)
      ? t('offline.sheetsNotYet')
      : t('offline.squaresSoFar', { n: count(saved.tiles), of: count(saved.planned ?? saved.tiles) }))
    else if (saved.missing) notes.push(t('offline.squaresMissing', { count: saved.missing, n: count(saved.missing) }))
    if (saved.capped) notes.push(t('offline.capped'))
    if (estate && !sameBox(estate.box, saved.box)) notes.push(t('offline.boxChanged'))
    if (!part && Date.now() - Date.parse(saved.at) > 7 * 86_400_000) notes.push(t('offline.old'))
  }
  const status = saved === undefined ? t('alertsSet.checking')
    : saved ? `${part ? t('offline.partSaved') : t('offline.mapSaved')} · ${sizeLabel(saved.bytes)} · ${savedAge(saved.at)}`
      : leftovers ? t('offline.leftovers')
        : t('offline.notSaved')
  const outcome = removed ? { ok: true, text: t('offline.removed') } : job.outcome
  const farOff = estate?.cameras_left_out ?? []

  return <section aria-labelledby="msheet-offline" className="msheet-offline">
    <h3 id="msheet-offline">{t('offline.title')}</h3>
    <p className={`msheet-status${saved && !part ? ' msheet-status--saved' : ''}`} role="status">{status}</p>
    {saved && !part && <p className="msheet-note">{t('offline.withAll', { base: baseLabel(saved.base) })}</p>}
    {notes.map(n => <p key={n} className="msheet-note msheet-note--warn">{n}</p>)}

    {/* Two savable map types: say which. Esri's world imagery can't be kept. */}
    <div className="msheet-segments msheet-segments--two" role="radiogroup" aria-label={t('offline.typeToSave')}>
      {SAVABLE.map(b => <button key={b} type="button" role="radio" aria-checked={(busy ? job.base : choice) === b} disabled={busy} onClick={() => { setChoice(b); setChosen(true) }}>{baseLabel(b)}</button>)}
    </div>
    {base === 'world' && <p className="msheet-note">{t('offline.worldNo', { base: baseLabel('world') })}</p>}

    {busy ? <div className="msheet-progress" role="status">
      <span>{progressWords(progress)}</span>
      <button type="button" className="map-button" onClick={stopDownload}>{t('offline.stop')}</button>
    </div> : <button type="button" className="map-button map-button--primary map-button--big" disabled={!box} onClick={run}>
      {part && saved?.base === choice ? t('offline.finish') : saved || leftovers ? t('offline.again') : t('offline.download')}
    </button>}
    {busy && <p className="msheet-note">{t('offline.carriesOn')}</p>}
    {p && !busy && <details className="msheet-numbers">
      <summary>{t('offline.about', { size: sizeLabel(p.bytes) })}</summary>
      <p>{estate
        ? t('offline.squaresOver', { n: count(p.tiles), min: p.minZoom, max: p.maxZoom, area: km(estate) })
        : t('offline.squares', { n: count(p.tiles), min: p.minZoom, max: p.maxZoom })}</p>
    </details>}
    {!box && estateErr && <p className="msheet-note msheet-note--warn">{estateErr} {t('offline.needsSignal')}</p>}
    {outcome && !busy && (outcome.ok ? <p className="msheet-note" role="status">{outcome.text}</p> : <InlineError text={outcome.text} />)}
    {(saved || leftovers > 0) && !busy && (asking
      ? <div className="map-confirm" role="group" aria-label={t('offline.removeLabel')}>
          <p>{t('offline.removeAsk')}</p>
          <div className="map-actions"><button type="button" className="map-button" onClick={remove}>{t('common.remove')}</button><button type="button" className="map-button" onClick={() => setAsking(false)}>{t('common.keep')}</button></div>
        </div>
      : <button type="button" className="map-link" onClick={() => setAsking(true)}>{t('offline.removeFromPhone')}</button>)}

    {admin && estate && <div className="msheet-box">
      <p className="msheet-note">
        {t(estate.box_set ? 'offline.boxSet' : 'offline.boxDrawn', { area: km(estate) })}
      </p>
      {farOff.length > 0 && <p className="msheet-note msheet-note--warn">{farWords(farOff)}</p>}
      <div className="map-actions">
        <button type="button" className="map-button" disabled={boxBusy} onClick={() => { const v = viewBox(); if (v) setBox(v) }}>{t('offline.useView')}</button>
        {estate.box_set && <button type="button" className="map-button" disabled={boxBusy} onClick={() => setBox(null)}>{t('offline.roundAll')}</button>}
      </div>
      {boxErr && <InlineError text={boxErr} />}
    </div>}
  </section>
}
