import { CameraIcon } from '@phosphor-icons/react/dist/csr/Camera'
import { MapPinPlusIcon } from '@phosphor-icons/react/dist/csr/MapPinPlus'
import { MountainsIcon } from '@phosphor-icons/react/dist/csr/Mountains'
import { NavigationArrowIcon } from '@phosphor-icons/react/dist/csr/NavigationArrow'
import { PolygonIcon } from '@phosphor-icons/react/dist/csr/Polygon'
import { RulerIcon } from '@phosphor-icons/react/dist/csr/Ruler'
import type { ReactNode } from 'react'
import SwitchRow from '../components/SwitchRow'
import { t } from '../i18n'
import { VIEWS, type View } from './activity'
import { BASES, CALLOUT_ZOOM, CATASTRO_MINZOOM, type BaseId, type MapPrefs } from './basemaps'
import type { Camera } from './geometry'
import type { Layers } from './layers'
import type { Box } from './offline'
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
  offline: { cameras: Camera[]; viewBox: () => Box | null; onBox: (box: Box | null) => void }
}) {
  const layer = (key: keyof Layers) => (on: boolean) => onPrefs({ ...prefs, layers: { ...prefs.layers, [key]: on } })
  return <div className="msheet">
    <section aria-labelledby="msheet-view">
      <h3 id="msheet-view">{t('msheet.view')}</h3>
      <div className="msheet-segments" role="radiogroup" aria-label={t('msheet.view')}>
        {VIEWS.map(v => <button key={v.id} type="button" role="radio" aria-checked={view === v.id} onClick={() => onView(v.id)}>{t(v.label)}</button>)}
      </div>
      <p className="msheet-note">{t(VIEWS.find(v => v.id === view)?.note ?? 'view.camerasNote')}</p>
    </section>

    <section aria-labelledby="msheet-type">
      <h3 id="msheet-type">{t('msheet.type')}</h3>
      <div className="msheet-segments" role="radiogroup" aria-label={t('msheet.type')}>
        {BASES.map(b => <button key={b.id} type="button" role="radio" aria-checked={prefs.base === b.id} onClick={() => prefs.base === b.id ? onRetryBase() : onPrefs({ ...prefs, base: b.id as BaseId })}>{t(b.label)}</button>)}
      </div>
      {baseNote && <p className="msheet-note msheet-note--warn" role="status">{baseNote}</p>}
      <SwitchRow label={t('msheet.catastro')} on={prefs.catastro} onChange={on => onPrefs({ ...prefs, catastro: on })}
        note={catastroNote ?? (prefs.catastro && zoom < CATASTRO_MINZOOM ? t('msheet.zoomCloser') : t('msheet.catastroNote'))} />
    </section>

    <section aria-labelledby="msheet-show">
      <h3 id="msheet-show">{t('msheet.show')}</h3>
      <div className="msheet-key" aria-label={t('msheet.key')}>
        <span><i className="key-stand" />{t('map.stand')}</span><span><i className="key-camera" />{t('map.camera')}</span>
        <span><i className="key-wind key-wind--clean" />{t('msheet.keyAway')}</span><span><i className="key-wind key-wind--carries" />{t('msheet.keyReaches')}</span>
      </div>
      <SwitchRow label={t('msheet.photos')} note={prefs.layers.photos && zoom < CALLOUT_ZOOM ? t('msheet.zoomCloser') : t('msheet.photosNote')}
        on={prefs.layers.photos} onChange={layer('photos')} />
      <SwitchRow label={t('msheet.wind')} note={t('msheet.windNote')} on={prefs.layers.wind} onChange={layer('wind')} />
      <SwitchRow label={t('msheet.bedding')} note={t('msheet.beddingNote')} on={prefs.layers.bedding} onChange={layer('bedding')} />
      <SwitchRow label={t('msheet.safe')} note={t('msheet.safeNote')} on={prefs.layers.exposure} onChange={layer('exposure')} />
      {/* Not lines from bedding to every camera near it (audit G-25): the replay's
          "likely went this way", seen on more than one night. */}
      <SwitchRow label={t('msheet.paths')} note={paths ?? t('msheet.pathsNote')}
        on={prefs.layers.routes} onChange={layer('routes')} />
    </section>

    <section aria-labelledby="msheet-tools">
      <h3 id="msheet-tools">{t('msheet.tools')}</h3>
      <ToolRow icon={<RulerIcon size={22} />} label={measuring ? t('msheet.stopMeasure') : t('msheet.measure')} note={t('msheet.measureNote')} onClick={onMeasure} />
      <ToolRow icon={<NavigationArrowIcon size={22} />} label={meOn ? t('msheet.hideMe') : t('msheet.showMe')} note={t('msheet.meNote')} onClick={onMe} />
      {admin && <>
        <ToolRow icon={<MapPinPlusIcon size={22} />} label={t('msheet.addStand')} note={t('msheet.addStandNote')} onClick={onAddStand} />
        <ToolRow icon={<PolygonIcon size={22} />} label={t('msheet.drawBedding')} note={t('msheet.drawBeddingNote')} onClick={onDrawBedding} />
        {unplaced.map(u => <ToolRow key={`${u.kind}-${u.id}`} icon={u.kind === 'camera' ? <CameraIcon size={22} /> : <MapPinPlusIcon size={22} />} label={t('msheet.place', { name: u.name })} note={u.kind === 'camera' ? t('msheet.cameraNotPlaced') : t('msheet.standNotPlaced')} onClick={() => onPlace(u)} />)}
        {(terrain.needed || terrain.outside.length > 0 || terrain.busy || terrain.err) && <>
          <ToolRow icon={<MountainsIcon size={22} />} label={terrain.busy ? t('msheet.terrainLoading') : terrain.needed ? t('msheet.terrainLoad') : t('msheet.terrainAgain')}
            note={terrain.busy ? t('msheet.terrainBusy')
              : terrain.needed ? t('msheet.terrainNeeded')
                : t('msheet.terrainOutside', { count: terrain.outside.length, names: terrain.outside.join(', ') })}
            onClick={terrain.onLoad} disabled={terrain.busy} />
          {terrain.err && <p className="msheet-note msheet-note--warn" role="alert">{terrain.err}</p>}
        </>}
      </>}
      {!admin && unplaced.length > 0 && <p className="msheet-note">{t('msheet.notPlaced', { count: unplaced.length, names: unplaced.map(u => u.name).join(', ') })}</p>}
    </section>

    <OfflinePanel admin={admin} cameras={offline.cameras} base={prefs.base} viewBox={offline.viewBox} onBox={offline.onBox} />

    <section aria-labelledby="msheet-size">
      <h3 id="msheet-size">{t('msheet.size')}</h3>
      <SwitchRow label={t('msheet.bigPins')} on={prefs.bigPins} onChange={on => onPrefs({ ...prefs, bigPins: on })} />
    </section>
  </div>
}
