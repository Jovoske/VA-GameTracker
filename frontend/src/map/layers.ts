import type { Map, StyleSpecification, GeoJSONSource, ExpressionSpecification } from 'maplibre-gl'
import { windGeometry, type Camera, type MapData } from './geometry'
export const style: StyleSpecification = { version: 8, sources: { satellite: { type: 'raster', tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], tileSize: 256, attribution: 'Imagery © Esri' } }, layers: [{ id: 'satellite', type: 'raster', source: 'satellite', paint: { 'raster-saturation': -.35, 'raster-brightness-max': .85 } }] }
export type Layers = { bedding: boolean; wind: boolean; exposure: boolean; routes: boolean }
export const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const colors: ExpressionSpecification = ['match', ['get', 'status'], 'clean', '#a6c7b1', 'scent_carries', '#e2ad83', '#a2aaa5']
export function setSource(map: Map, id: string, features: GeoJSON.Feature[]) { (map.getSource(id) as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features }) }
export function addLayers(map: Map) {
  for (const id of ['bedding', 'wind', 'cones', 'exposure', 'routes', 'draft']) map.addSource(id, { type: 'geojson', data: empty })
  map.addLayer({ id: 'exposure', type: 'circle', source: 'exposure', paint: { 'circle-color': ['case', ['get', 'safe'], '#a6c7b1', '#e2ad83'], 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 3, 16, 14], 'circle-opacity': .18 } })
  map.addLayer({ id: 'bedding-fill', type: 'fill', source: 'bedding', paint: { 'fill-color': '#ccb88b', 'fill-opacity': .12 } })
  map.addLayer({ id: 'bedding-line', type: 'line', source: 'bedding', paint: { 'line-color': '#ccb88b', 'line-width': 1.5, 'line-dasharray': [3, 2] } })
  map.addLayer({ id: 'cones-fill', type: 'fill', source: 'cones', paint: { 'fill-color': colors, 'fill-opacity': .12 } })
  map.addLayer({ id: 'cones-line', type: 'line', source: 'cones', paint: { 'line-color': colors, 'line-width': 1, 'line-opacity': .5 } })
  map.addLayer({ id: 'routes-line', type: 'line', source: 'routes', paint: { 'line-color': '#a6bfc7', 'line-width': 1.5, 'line-dasharray': [2, 3], 'line-opacity': .7 } })
  map.addLayer({ id: 'wind-halo', type: 'line', source: 'wind', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#15231b', 'line-width': 5, 'line-opacity': .6 } })
  map.addLayer({ id: 'wind-line', type: 'line', source: 'wind', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': colors, 'line-width': 2 } })
  map.addLayer({ id: 'draft-line', type: 'line', source: 'draft', filter: ['==', '$type', 'LineString'], paint: { 'line-color': '#f2dfb5', 'line-width': 2, 'line-dasharray': [2, 2] } })
  map.addLayer({ id: 'draft-points', type: 'circle', source: 'draft', filter: ['==', '$type', 'Point'], paint: { 'circle-color': '#f2dfb5', 'circle-radius': 4, 'circle-stroke-color': '#15231b', 'circle-stroke-width': 2 } })
}
export function renderLayers(map: Map, data: MapData, layers: Layers, selectedStand?: string) {
  setSource(map, 'bedding', layers.bedding ? data.zones.map(z => ({ type: 'Feature', properties: { id: z.id }, geometry: z.polygon })) : [])
  const winds: GeoJSON.Feature[] = [], cones: GeoJSON.Feature[] = []
  if (layers.wind) for (const stand of data.stands) {
    const g = windGeometry(stand, data.scent_range_m)
    if (!g) continue
    winds.push({ type: 'Feature', properties: { status: stand.wind.status }, geometry: g.arrow })
    if (stand.id === selectedStand) cones.push({ type: 'Feature', properties: { status: stand.wind.status }, geometry: g.cone })
  }
  setSource(map, 'wind', winds); setSource(map, 'cones', cones)
  setSource(map, 'exposure', layers.exposure ? data.safe_ground.cells.map(c => ({ type: 'Feature', properties: { safe: c.safe }, geometry: { type: 'Point', coordinates: [c.lon, c.lat] } })) : [])
  setSource(map, 'routes', layers.routes ? data.routes.map(r => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[r.from.lon, r.from.lat], [r.to.lon, r.to.lat]] } })) : [])
}
export function fitEstate(map: Map, data: MapData, cameras: Camera[]) {
  const points: [number, number][] = [
    ...cameras.flatMap(c => c.lat != null && c.lng != null ? [[c.lng, c.lat] as [number, number]] : []),
    ...data.stands.flatMap(s => s.lat != null && s.lon != null ? [[s.lon, s.lat] as [number, number]] : []),
    ...data.zones.flatMap(z => z.polygon.coordinates[0].map(p => [p[0], p[1]] as [number, number])),
  ]
  if (points.length) map.fitBounds([[Math.min(...points.map(p => p[0])), Math.min(...points.map(p => p[1]))], [Math.max(...points.map(p => p[0])), Math.max(...points.map(p => p[1]))]], { padding: 64, maxZoom: 16, duration: 0 })
}
