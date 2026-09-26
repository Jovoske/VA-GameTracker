import type { Map, GeoJSONSource, ExpressionSpecification } from 'maplibre-gl'
import { validLngLat, windGeometry, windToken, type Camera, type MapData } from './geometry'
export type Layers = { bedding: boolean; wind: boolean; exposure: boolean; routes: boolean }
export const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }

/**
 * GL paint can't read CSS variables, so the map asks the theme for its colours once,
 * when the layers are added. One palette for the whole app: change theme.css and the
 * map follows. The fallbacks are the same tokens, for a page that loaded no theme.
 */
function token(name: string, fallback: string): string {
  try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback } catch { return fallback }
}

export function setSource(map: Map, id: string, features: GeoJSON.Feature[]) { (map.getSource(id) as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features }) }
export function addLayers(map: Map) {
  const c = {
    bg: token('--bg', '#0E1311'), text: token('--text', '#E6EDEA'), sand: token('--sand', '#D9B370'),
    teal: token('--teal', '#3FB9B0'), camera: token('--camera', '#A9C2C8'),
    clean: token(windToken('clean'), '#6FCB7F'), carries: token(windToken('scent_carries'), '#E3A008'), quiet: token(windToken(''), '#8A9A92'),
  }
  const wind: ExpressionSpecification = ['match', ['get', 'status'], 'clean', c.clean, 'scent_carries', c.carries, c.quiet]
  for (const id of ['bedding', 'wind', 'cones', 'exposure', 'routes', 'me', 'measure', 'draft']) map.addSource(id, { type: 'geojson', data: empty })
  map.addLayer({ id: 'exposure', type: 'circle', source: 'exposure', paint: { 'circle-color': ['case', ['get', 'safe'], c.clean, c.carries], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 3, 16, 14], 'circle-opacity': .18 } })
  map.addLayer({ id: 'bedding-fill', type: 'fill', source: 'bedding', paint: { 'fill-color': c.sand, 'fill-opacity': .12 } })
  map.addLayer({ id: 'bedding-line', type: 'line', source: 'bedding', paint: { 'line-color': c.sand, 'line-width': 1.5, 'line-dasharray': [3, 2] } })
  map.addLayer({ id: 'cones-fill', type: 'fill', source: 'cones', paint: { 'fill-color': wind, 'fill-opacity': .12 } })
  map.addLayer({ id: 'cones-line', type: 'line', source: 'cones', paint: { 'line-color': wind, 'line-width': 1, 'line-opacity': .5 } })
  map.addLayer({ id: 'routes-line', type: 'line', source: 'routes', paint: { 'line-color': c.camera, 'line-width': 1.5, 'line-dasharray': [2, 3], 'line-opacity': .7 } })
  map.addLayer({ id: 'wind-halo', type: 'line', source: 'wind', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.bg, 'line-width': 5, 'line-opacity': .6 } })
  map.addLayer({ id: 'wind-line', type: 'line', source: 'wind', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': wind, 'line-width': 2 } })
  // Your own position: how sure the phone is, as a faint teal disc. The dot itself is a marker.
  map.addLayer({ id: 'me-accuracy', type: 'fill', source: 'me', paint: { 'fill-color': c.teal, 'fill-opacity': .08 } })
  map.addLayer({ id: 'me-accuracy-line', type: 'line', source: 'me', paint: { 'line-color': c.teal, 'line-width': 1, 'line-opacity': .45 } })
  map.addLayer({ id: 'measure-halo', type: 'line', source: 'measure', filter: ['==', '$type', 'LineString'], layout: { 'line-cap': 'round' }, paint: { 'line-color': c.bg, 'line-width': 5, 'line-opacity': .7 } })
  map.addLayer({ id: 'measure-line', type: 'line', source: 'measure', filter: ['==', '$type', 'LineString'], layout: { 'line-cap': 'round' }, paint: { 'line-color': c.text, 'line-width': 2, 'line-dasharray': [2, 1.5] } })
  map.addLayer({ id: 'measure-points', type: 'circle', source: 'measure', filter: ['==', '$type', 'Point'], paint: { 'circle-color': c.text, 'circle-radius': 5, 'circle-stroke-color': c.bg, 'circle-stroke-width': 2 } })
  map.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': c.sand, 'fill-opacity': .14 } })
  map.addLayer({ id: 'draft-halo', type: 'line', source: 'draft', filter: ['==', '$type', 'LineString'], paint: { 'line-color': c.bg, 'line-width': 5, 'line-opacity': .6 } })
  map.addLayer({ id: 'draft-line', type: 'line', source: 'draft', filter: ['all', ['==', '$type', 'LineString'], ['!has', 'preview']], paint: { 'line-color': c.sand, 'line-width': 2.5 } })
  map.addLayer({ id: 'draft-preview', type: 'line', source: 'draft', filter: ['all', ['==', '$type', 'LineString'], ['has', 'preview']], paint: { 'line-color': c.text, 'line-width': 1.5, 'line-dasharray': [2, 2] } })
  map.addLayer({ id: 'draft-points', type: 'circle', source: 'draft', filter: ['==', '$type', 'Point'], paint: { 'circle-color': c.sand, 'circle-radius': 5, 'circle-stroke-color': c.bg, 'circle-stroke-width': 2 } })
}
export function renderLayers(map: Map, data: MapData, layers: Layers, selectedStand?: string) {
  // Only bedding is drawn as bedding. Other zone kinds can come in through the API (B-22).
  setSource(map, 'bedding', layers.bedding ? data.zones.filter(z => z.kind === 'bedding').map(z => ({ type: 'Feature', properties: { id: z.id }, geometry: z.polygon })) : [])
  const winds: GeoJSON.Feature[] = [], cones: GeoJSON.Feature[] = []
  if (layers.wind) for (const stand of data.stands) {
    if (!validLngLat(stand.lon, stand.lat)) continue
    const g = windGeometry(stand, data.scent_range_m)
    if (!g) continue
    winds.push({ type: 'Feature', properties: { status: stand.wind.status }, geometry: g.arrow })
    if (stand.id === selectedStand) cones.push({ type: 'Feature', properties: { status: stand.wind.status }, geometry: g.cone })
  }
  setSource(map, 'wind', winds); setSource(map, 'cones', cones)
  setSource(map, 'exposure', layers.exposure ? data.safe_ground.cells.map(c => ({ type: 'Feature', properties: { safe: c.safe }, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } })) : [])
  setSource(map, 'routes', layers.routes ? data.routes.map(r => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]] } })) : [])
}
export function fitEstate(map: Map, data: MapData, cameras: Camera[], duration = 0) {
  // A bad coordinate from the API must not throw here: fitBounds on lat 1000 blanks the page (B-08).
  const points: [number, number][] = [
    ...cameras.flatMap(c => validLngLat(c.lng, c.lat) ? [[c.lng!, c.lat!] as [number, number]] : []),
    ...data.stands.flatMap(s => validLngLat(s.lon, s.lat) ? [[s.lon!, s.lat!] as [number, number]] : []),
    ...data.zones.flatMap(z => z.polygon.coordinates[0].filter(p => validLngLat(p[0], p[1])).map(p => [p[0], p[1]] as [number, number])),
  ]
  if (points.length) map.fitBounds([[Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))], [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))]], { padding: 72, maxZoom: 16, duration })
}
