import { Link } from 'react-router-dom'
import { validLngLat, type Camera } from './geometry'

/**
 * A camera's sheet on the map.
 *
 * Kept in its own file on purpose: this is where the camera's own photos land next
 * (last photo, last night's visits, a strip of recent photos, its alert switch).
 * The header is what shows at the 112px peek, so it carries the one line that says
 * whether the camera is worth opening.
 */
export function CameraHeader({ camera }: { camera: Camera }) {
  const battery = camera.battery_pct == null ? 'Battery unknown' : `Battery ${camera.battery_pct}%`
  return <>
    <span className="map-eyebrow">Camera</span>
    <h2 className="bsheet-name">{camera.name}</h2>
    <p className="bsheet-meta">{camera.sightings} sighting{camera.sightings === 1 ? '' : 's'} · {battery}</p>
  </>
}

export function CameraBody({ camera, admin, onMove }: { camera: Camera; admin: boolean; onMove: () => void }) {
  const placed = validLngLat(camera.lng, camera.lat)
  return <>
    {!placed && <p className="map-detail-copy">Not on the map yet.{admin ? '' : ' An admin can place it.'}</p>}
    <Link className="map-button map-button--primary map-button--big" to={`/photos?camera=${encodeURIComponent(camera.id)}`}>See this camera’s photos</Link>
    {admin && <div className="map-actions map-actions--admin">
      <button type="button" className="map-button" onClick={onMove}>{placed ? 'Move' : 'Place it on the map'}</button>
    </div>}
  </>
}
