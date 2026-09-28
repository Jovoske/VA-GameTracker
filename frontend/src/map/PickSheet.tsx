import { t } from '../i18n'
import { PIN_ICONS, type PinRef } from './pins'

/**
 * "Which one?": a tap that landed on more than one pin. At estate zoom a camera
 * and the stand beside it share a spot on the screen, and neither should be
 * unreachable, so the sheet lists what is there and one tap opens it.
 */
export function PickHeader({ count }: { count: number }) {
  return <>
    <span className="map-eyebrow">{t('map.pickHere', { n: count })}</span>
    <h2 className="bsheet-name">{t('map.whichOne')}</h2>
  </>
}

export function PickBody({ pins, onPick }: { pins: PinRef[]; onPick: (pin: PinRef) => void }) {
  return <div className="map-pick">
    {pins.map(p => <button key={`${p.kind}-${p.id}`} type="button" className="msheet-row map-pick-row" onClick={() => onPick(p)}>
      <span className={`map-pick-icon map-pin--${p.kind}`} aria-hidden="true"><span className="map-pin-icon" dangerouslySetInnerHTML={{ __html: PIN_ICONS[p.kind] }} /></span>
      <span className="msheet-text"><span>{p.name}</span><small>{p.kind === 'camera' ? t('map.camera') : t('map.stand')}</small></span>
      <span className="msheet-chevron" aria-hidden="true">›</span>
    </button>)}
  </div>
}
