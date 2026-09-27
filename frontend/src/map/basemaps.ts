import type { Map, StyleSpecification } from 'maplibre-gl'
import { type Key, t } from '../i18n'
import type { Layers } from './layers'

/**
 * The pictures under the map, and the choices a hunter makes about them.
 *
 * Spain publishes better ground than any world imagery: IGN's PNOA orthophotos are
 * sharper over the estate than Esri's, the MTN topo shows tracks, streams and contour
 * lines, and Catastro draws every property line. All three are free public tile
 * services. Esri stays as "Aerial (world)" because it is also what the map falls back
 * to when the Spanish servers don't answer.
 *
 * Every base lives in the one style from the start and a choice only flips layer
 * visibility. Nothing here ever calls setStyle: that is what used to wipe the bedding
 * and wind layers (B-01). A hidden raster layer requests no tiles.
 */
export type BaseId = 'aerial' | 'topo' | 'world'
export const BASES: { id: BaseId; label: Key; source: string }[] = [
  { id: 'aerial', label: 'base.aerial', source: 'base-aerial' },
  { id: 'topo', label: 'base.topo', source: 'base-topo' },
  { id: 'world', label: 'base.world', source: 'base-world' },
]
export const baseSource = (id: BaseId) => BASES.find(b => b.id === id)!.source
export const baseLabel = (id: BaseId) => t(BASES.find(b => b.id === id)!.label)
export const BASE_SOURCES = BASES.map(b => b.source)
export const CATASTRO = 'catastro'
// Catastro only draws parcels from about this zoom; further out it sends blank tiles.
export const CATASTRO_MINZOOM = 15
// Camera photos show from this zoom in; further out each camera is its plain mark.
export const CALLOUT_ZOOM = 13

const WMTS = (service: string, layer: string, format: string) =>
  `https://www.ign.es/wmts/${service}?service=WMTS&request=GetTile&version=1.0.0&layer=${layer}&style=default&tilematrixset=GoogleMapsCompatible&tilematrix={z}&tilerow={y}&tilecol={x}&format=${format}`

// The picture each base asks for, {z}/{x}/{y} filled in by MapLibre, or by
// offline.ts for the copy a phone keeps (the saved key must be the same URL).
export const TILES: Record<BaseId, string> = {
  aerial: WMTS('pnoa-ma', 'OI.OrthoimageCoverage', 'image/jpeg'),
  topo: WMTS('mapa-raster', 'MTN', 'image/jpeg'),
  world: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
}
// maxzoom is the deepest level each service really has. Past it MapLibre stretches
// the last tiles instead of asking for ones that don't exist (B-24).
export const MAX_ZOOM: Record<BaseId, number> = { aerial: 19, topo: 17, world: 19 }

export function mapStyle(prefs: Pick<MapPrefs, 'base' | 'catastro'>): StyleSpecification {
  const visible = (on: boolean) => ({ visibility: on ? 'visible' as const : 'none' as const })
  return {
    version: 8,
    sources: {
      'base-aerial': { type: 'raster', tiles: [TILES.aerial], tileSize: 256, maxzoom: MAX_ZOOM.aerial, attribution: '© IGN-PNOA' },
      'base-topo': { type: 'raster', tiles: [TILES.topo], tileSize: 256, maxzoom: MAX_ZOOM.topo, attribution: '© IGN' },
      'base-world': { type: 'raster', tiles: [TILES.world], tileSize: 256, maxzoom: MAX_ZOOM.world, attribution: 'Imagery © Esri' },
      [CATASTRO]: { type: 'raster', tiles: ['https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=Catastro&STYLES=&SRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=TRUE'], tileSize: 256, minzoom: CATASTRO_MINZOOM, maxzoom: 20, attribution: '© Dirección General del Catastro' },
    },
    layers: [
      // Dimmed and desaturated: this is read at dusk, next to a dark UI.
      { id: 'base-aerial', type: 'raster', source: 'base-aerial', layout: visible(prefs.base === 'aerial'), paint: { 'raster-saturation': -.3, 'raster-brightness-max': .85 } },
      { id: 'base-topo', type: 'raster', source: 'base-topo', layout: visible(prefs.base === 'topo'), paint: { 'raster-saturation': -.15, 'raster-brightness-max': .78 } },
      { id: 'base-world', type: 'raster', source: 'base-world', layout: visible(prefs.base === 'world'), paint: { 'raster-saturation': -.35, 'raster-brightness-max': .85 } },
      { id: CATASTRO, type: 'raster', source: CATASTRO, layout: visible(prefs.catastro), paint: { 'raster-opacity': .7 } },
    ],
  }
}

export function showBase(map: Map, id: BaseId) {
  for (const b of BASES) if (map.getLayer(b.source)) map.setLayoutProperty(b.source, 'visibility', b.id === id ? 'visible' : 'none')
}
/**
 * Ask again for the base tiles that failed, keeping the ones that loaded.
 *
 * map.refreshTiles() is the obvious call, but in MapLibre 5.24 it marks a failed
 * raster tile "expired", which counts as having data, so the next frame tries to draw
 * a texture that was never made and throws. Hiding the layer for one frame drops the
 * failed tiles instead; showing it again asks for fresh ones and takes the loaded ones
 * straight back from the tile cache. Nothing else on the map is touched.
 */
export function retryBase(map: Map, id: BaseId, stillShown: () => boolean) {
  const layer = baseSource(id)
  if (!map.getLayer(layer)) return
  map.setLayoutProperty(layer, 'visibility', 'none')
  map.once('render', () => { if (map.getLayer(layer) && stillShown()) map.setLayoutProperty(layer, 'visibility', 'visible') })
}
export function showCatastro(map: Map, on: boolean) {
  if (map.getLayer(CATASTRO)) map.setLayoutProperty(CATASTRO, 'visibility', on ? 'visible' : 'none')
}

// ── remembered on this phone ──
// Per-viewer conveniences only. Storage can be missing or throw (private mode,
// blocked site data), and the map must still open with sensible defaults.
export type MapPrefs = { base: BaseId; catastro: boolean; bigPins: boolean; layers: Layers }
const DEFAULT_LAYERS: Layers = { bedding: true, wind: true, exposure: false, routes: false, photos: true }
const KEY = { base: 'gs_map_base', catastro: 'gs_map_catastro', bigPins: 'gs_map_big_pins', layers: 'gs_map_layers' }

function read(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function write(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* a convenience, never a requirement */ }
}
export function readPrefs(): MapPrefs {
  const base = read(KEY.base)
  let layers = DEFAULT_LAYERS
  try {
    const saved = JSON.parse(read(KEY.layers) ?? 'null')
    if (saved && typeof saved === 'object') layers = { ...DEFAULT_LAYERS, ...Object.fromEntries(Object.entries(saved).filter(([k, v]) => k in DEFAULT_LAYERS && typeof v === 'boolean')) }
  } catch { /* keep the defaults */ }
  return {
    base: BASES.some(b => b.id === base) ? base as BaseId : 'aerial',
    catastro: read(KEY.catastro) === '1',
    bigPins: read(KEY.bigPins) === '1',
    layers,
  }
}
export function writePrefs(prefs: MapPrefs) {
  write(KEY.base, prefs.base)
  write(KEY.catastro, prefs.catastro ? '1' : '0')
  write(KEY.bigPins, prefs.bigPins ? '1' : '0')
  write(KEY.layers, JSON.stringify(prefs.layers))
}
