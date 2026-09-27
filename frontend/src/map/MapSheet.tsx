import { CameraIcon } from '@phosphor-icons/react/dist/csr/Camera'
import { MapPinPlusIcon } from '@phosphor-icons/react/dist/csr/MapPinPlus'
import { MountainsIcon } from '@phosphor-icons/react/dist/csr/Mountains'
import { NavigationArrowIcon } from '@phosphor-icons/react/dist/csr/NavigationArrow'
import { PolygonIcon } from '@phosphor-icons/react/dist/csr/Polygon'
import { RulerIcon } from '@phosphor-icons/react/dist/csr/Ruler'
import type { ReactNode } from 'react'
import SwitchRow from '../components/SwitchRow'
import { VIEWS, type View } from './activity'
import { BASES, CALLOUT_ZOOM, CATASTRO_MINZOOM, type BaseId, type MapPrefs } from './basemaps'
import type { Camera } from './geometry'
import type { Layers } from './layers'
import type { Box, Saved } from './offline'
import OfflinePanel from './OfflinePanel'

export type Unplaced = { kind: 'stand' | 'camera'; id: string; name: string }

function ToolRow({ icon, label, note, onClick, disabled }: { icon: ReactNode; label: string; note?: string; onClick: () => void; disabled?: boolean }) {
  return <button type="button" className="msheet-row" onClick={onClick} disabled={disabled}>
    <span className="msheet-lead" aria-hidden="true">{icon}</span>
    <span className="msheet-text"><span>{label}</span>{note && <small>{note}</small>}</span>
    <span className="msheet-chevron" aria-hidden="true">›</span>
  </button>
}

/**
 * Everything about how the map looks, in one sheet: what the cameras show (their
 * photos, where the game is, or a night played back), which picture is underneath,
 * what is drawn on it, the tools, and one size switch. WeHunt's settings sheet, cut
 * down to what a handful of hunters on one estate actually change.
 */
export default function MapSheet({ view, onView, prefs, onPrefs, onRetryBase, zoom, baseNote, catastroNote, admin, measuring, meOn, onMeasure, onMe, onAddStand, onDrawBedding, onPlace, unplaced, terrain, paths, offline }: {
  view: View
  /** Choosing a view closes the sheet and shows it. */
  onView: (view: View) => void
  prefs: MapPrefs
  onPrefs: (next: MapPrefs) => void
  /** Tapping the map type that is already chosen asks for its picture again. */
  onRetryBase: () => void
  zoom: number
  baseNote: string | null
  catastroNote: string | null
  admin: boolean
  measuring: boolean
  meOn: boolean
  onMeasure: () => void
  onMe: () => void
  onAddStand: () => void
  onDrawBedding: () => void
  onPlace: (item: Unplaced) => void
  unplaced: Unplaced[]
  /** The hill shape: missing, or not reaching some stands (their names), and loading it. */
  terrain: { needed: boolean; outside: string[]; busy: boolean; err: string; onLoad: () => void }
  /** How the likely paths layer is doing: a line under its switch, or null. */
  paths: string | null
  offline: { cameras: Camera[]; viewBox: () => Box | null; onBox: (box: Box | null) => void; onSaved: (saved: Saved | null) => void }
}) {
  const layer = (key: keyof Layers) => (on: boolean) => onPrefs({ ...prefs, layers: { ...prefs.layers, [key]: on } })
  return <div className="msheet">
    <section aria-labelledby="msheet-view">
      <h3 id="msheet-view">View</h3>
      <div className="msheet-segments" role="radiogroup" aria-label="View">
        {VIEWS.map(v => <button key={v.id} type="button" role="radio" aria-checked={view === v.id} onClick={() => onView(v.id)}>{v.label}</button>)}
      </div>
      <p className="msheet-note">{VIEWS.find(v => v.id === view)?.note}</p>
    </section>

    <section aria-labelledby="msheet-type">
      <h3 id="msheet-type">Map type</h3>
      <div className="msheet-segments" role="radiogroup" aria-label="Map type">
        {BASES.map(b => <button key={b.id} type="button" role="radio" aria-checked={prefs.base === b.id} onClick={() => prefs.base === b.id ? onRetryBase() : onPrefs({ ...prefs, base: b.id as BaseId })}>{b.label}</button>)}
      </div>
      {baseNote && <p className="msheet-note msheet-note--warn" role="status">{baseNote}</p>}
      <SwitchRow label="Property lines (Catastro)" on={prefs.catastro} onChange={on => onPrefs({ ...prefs, catastro: on })}
        note={catastroNote ?? (prefs.catastro && zoom < CATASTRO_MINZOOM ? 'Zoom in closer to see them.' : 'Every parcel boundary, from the land registry.')} />
    </section>

    <section aria-labelledby="msheet-show">
      <h3 id="msheet-show">Show on map</h3>
      <div className="msheet-key" aria-label="What the marks mean">
        <span><i className="key-stand" />Stand</span><span><i className="key-camera" />Camera</span>
        <span><i className="key-wind key-wind--clean" />Scent goes away from bedding</span><span><i className="key-wind key-wind--carries" />Scent reaches bedding</span>
      </div>
      <SwitchRow label="Camera photos" note={prefs.layers.photos && zoom < CALLOUT_ZOOM ? 'Zoom in closer to see them.' : 'Each camera’s latest animal photo, and how many are new to you.'}
        on={prefs.layers.photos} onChange={layer('photos')} />
      <SwitchRow label="Wind arrows" note="Where scent goes from each stand." on={prefs.layers.wind} onChange={layer('wind')} />
      <SwitchRow label="Bedding" note="Where the animals lie up." on={prefs.layers.bedding} onChange={layer('bedding')} />
      <SwitchRow label="Scent-safe ground" note="About scent reaching bedding, not shooting safety." on={prefs.layers.exposure} onChange={layer('exposure')} />
      {/* Not lines from bedding to every camera near it (audit G-25): the replay's
          "likely went this way", seen on more than one night. */}
      <SwitchRow label="Likely paths" note={paths ?? 'Where the same kind of animal went on from one camera to the next within 3 h, on 2 or more nights this month. A guess, not a track.'}
        on={prefs.layers.routes} onChange={layer('routes')} />
    </section>

    <section aria-labelledby="msheet-tools">
      <h3 id="msheet-tools">Tools</h3>
      <ToolRow icon={<RulerIcon size={22} />} label={measuring ? 'Stop measuring' : 'Measure'} note="Tap two points on the map." onClick={onMeasure} />
      <ToolRow icon={<NavigationArrowIcon size={22} />} label={meOn ? 'Hide where I am' : 'Show where I am'} note="Stays on this phone. Nothing is sent." onClick={onMe} />
      {admin && <>
        <ToolRow icon={<MapPinPlusIcon size={22} />} label="Add a stand" note="Put the cross where you sit." onClick={onAddStand} />
        <ToolRow icon={<PolygonIcon size={22} />} label="Draw bedding" note="Corner by corner, with the cross." onClick={onDrawBedding} />
        {unplaced.map(u => <ToolRow key={`${u.kind}-${u.id}`} icon={u.kind === 'camera' ? <CameraIcon size={22} /> : <MapPinPlusIcon size={22} />} label={`Place ${u.name}`} note={`This ${u.kind} isn’t on the map yet.`} onClick={() => onPlace(u)} />)}
        {(terrain.needed || terrain.outside.length > 0 || terrain.busy || terrain.err) && <>
          <ToolRow icon={<MountainsIcon size={22} />} label={terrain.busy ? 'Loading the hill shape…' : terrain.needed ? 'Load the hill shape' : 'Load the hill shape again'}
            note={terrain.busy ? 'It takes up to a minute. You can use the map meanwhile.'
              : terrain.needed ? 'Gives wind advice on calm nights.'
                : `${terrain.outside.join(', ')} ${terrain.outside.length === 1 ? 'is' : 'are'} outside it, so ${terrain.outside.length === 1 ? 'it gets' : 'they get'} no slope wind.`}
            onClick={terrain.onLoad} disabled={terrain.busy} />
          {terrain.err && <p className="msheet-note msheet-note--warn" role="alert">{terrain.err}</p>}
        </>}
      </>}
      {!admin && unplaced.length > 0 && <p className="msheet-note">{unplaced.map(u => u.name).join(', ')} {unplaced.length === 1 ? 'isn’t' : 'aren’t'} on the map yet. An admin can place {unplaced.length === 1 ? 'it' : 'them'}.</p>}
    </section>

    <OfflinePanel admin={admin} cameras={offline.cameras} base={prefs.base} viewBox={offline.viewBox} onBox={offline.onBox} onSaved={offline.onSaved} />

    <section aria-labelledby="msheet-size">
      <h3 id="msheet-size">Size</h3>
      <SwitchRow label="Bigger pins and names" on={prefs.bigPins} onChange={on => onPrefs({ ...prefs, bigPins: on })} />
    </section>
  </div>
}
