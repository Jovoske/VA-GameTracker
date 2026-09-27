import type { Map } from 'maplibre-gl'
import { useEffect, useState } from 'react'
import { formatDistance } from './geometry'

const MAX_PX = 84

/** A round number of metres that fits in `MAX_PX` at the map's centre. */
function scaleAt(map: Map): { label: string; px: number } {
  const lat = map.getCenter().lat
  const metresPerPx = 40075016.686 * Math.cos(lat * Math.PI / 180) / (512 * 2 ** map.getZoom())
  const most = metresPerPx * MAX_PX
  const pow = 10 ** Math.floor(Math.log10(most))
  const nice = [5, 2, 1].map(n => n * pow).find(n => n <= most) ?? pow
  return { label: formatDistance(nice), px: Math.round(nice / metresPerPx) }
}

/** The scale as a small pill at the top of the map, WeHunt-style. */
export default function ScalePill({ map }: { map: Map | null }) {
  const [scale, setScale] = useState<{ label: string; px: number } | null>(null)
  useEffect(() => {
    if (!map) return
    let frame = 0
    const update = () => { if (!frame) frame = requestAnimationFrame(() => { frame = 0; setScale(scaleAt(map)) }) }
    update()
    map.on('move', update)
    return () => { map.off('move', update); cancelAnimationFrame(frame) }
  }, [map])
  if (!scale) return null
  return <div className="map-scale" aria-label={`Scale: this bar is ${scale.label}`} role="img">
    <span>{scale.label}</span><i style={{ width: scale.px }} />
  </div>
}
