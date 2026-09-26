import maplibregl, { type Map } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { circle } from './geometry'
import { setSource } from './layers'

type Fix = { lng: number; lat: number; accuracy: number; heading: number | null }

/**
 * "Me": your own position on your own map, and nowhere else.
 *
 * It is read from the phone and drawn here. Nothing is sent to the server or shown
 * to anyone else; sharing positions with the group is a later, separate decision.
 * A white dot with a teal ring (not WeHunt's neon lime, which wrecks night vision),
 * a heading triangle when the phone knows which way you are moving, and a faint
 * disc for how sure it is.
 */
export function useMyPosition(map: Map | null, ready: boolean) {
  const [on, setOn] = useState(false)
  const [message, setMessage] = useState('')
  const [fix, setFix] = useState<Fix | null>(null)
  const marker = useRef<maplibregl.Marker | null>(null)
  const centred = useRef(false)

  useEffect(() => {
    if (!on) { setFix(null); return }
    if (!('geolocation' in navigator)) { setMessage('This browser can’t show where you are.'); setOn(false); return }
    centred.current = false
    setMessage('Finding where you are…')
    const watch = navigator.geolocation.watchPosition(p => {
      const heading = p.coords.heading
      setFix({ lng: p.coords.longitude, lat: p.coords.latitude, accuracy: p.coords.accuracy, heading: heading != null && Number.isFinite(heading) ? heading : null })
      setMessage('')
    }, err => {
      if (err.code === err.PERMISSION_DENIED) {
        setMessage('Location is off for GameSense. Allow it in your phone’s settings to see where you are.')
        setOn(false)
      } else setMessage('Your phone can’t find where you are right now. Try again in the open.')
    }, { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 })
    return () => navigator.geolocation.clearWatch(watch)
  }, [on])

  useEffect(() => {
    if (!map || !ready) return
    if (!fix) {
      marker.current?.remove(); marker.current = null
      if (map.getSource('me')) setSource(map, 'me', [])
      return
    }
    if (!marker.current) {
      const el = document.createElement('div')
      el.className = 'me-dot'
      el.setAttribute('role', 'img'); el.setAttribute('aria-label', 'You are here')
      el.innerHTML = '<span class="me-heading"></span><span class="me-core"></span>'
      marker.current = new maplibregl.Marker({ element: el, rotationAlignment: 'map' }).setLngLat([fix.lng, fix.lat]).addTo(map)
    }
    marker.current.setLngLat([fix.lng, fix.lat])
    marker.current.setRotation(fix.heading ?? 0)
    marker.current.getElement().classList.toggle('has-heading', fix.heading != null)
    setSource(map, 'me', [{ type: 'Feature', properties: {}, geometry: circle([fix.lng, fix.lat], Math.max(5, fix.accuracy)) }])
    if (!centred.current) {
      centred.current = true
      map.easeTo({ center: [fix.lng, fix.lat], zoom: Math.max(map.getZoom(), 15) })
    }
  }, [map, ready, fix])
  useEffect(() => () => { marker.current?.remove(); marker.current = null }, [])

  return { on, toggle: () => { setMessage(''); setOn(v => !v) }, message, clearMessage: () => setMessage(''), fix }
}
