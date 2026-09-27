import maplibregl, { type Map } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import { circle } from './geometry'
import { setSource } from './layers'

type Fix = { lng: number; lat: number; accuracy: number; heading: number | null }
// Faster than a slow walk, the GPS course is the way you are going. Slower, it is noise.
const MOVING_MS = 1
type OrientationEventWithCompass = DeviceOrientationEvent & { webkitCompassHeading?: number }
type OrientationPermission = { requestPermission?: () => Promise<'granted' | 'denied'> }

/** Which way the top of the phone points, clockwise from north, or null if the phone can't say. */
function compassHeading(e: OrientationEventWithCompass): number | null {
  const screen = (window.screen?.orientation?.angle ?? 0)
  // iPhone: already a compass heading. Android: alpha against true north when absolute.
  const raw = typeof e.webkitCompassHeading === 'number' ? e.webkitCompassHeading
    : e.absolute && e.alpha != null ? 360 - e.alpha : null
  return raw == null || !Number.isFinite(raw) ? null : (raw + screen + 360) % 360
}

/**
 * "Me": your own position on your own map, and nowhere else.
 *
 * It is read from the phone and drawn here. Nothing is sent to the server or shown
 * to anyone else; sharing positions with the group is a later, separate decision.
 * A white dot with a teal ring (not WeHunt's neon lime, which wrecks night vision),
 * a faint disc for how sure the phone is, and a heading triangle: the direction you
 * are walking while you move, and the phone's compass while you stand still.
 */
export function useMyPosition(map: Map | null, ready: boolean) {
  const [on, setOn] = useState(false)
  const [message, setMessage] = useState('')
  const [fix, setFix] = useState<Fix | null>(null)
  const marker = useRef<maplibregl.Marker | null>(null)
  const centred = useRef(false)
  const compass = useRef<number | null>(null)
  const fixRef = useRef(fix); fixRef.current = fix

  // Point the triangle. Called on every compass reading, so it touches the marker
  // directly rather than re-rendering the page sixty times a second.
  const aim = () => {
    const m = marker.current
    if (!m) return
    const heading = fixRef.current?.heading ?? compass.current
    if (heading != null) m.setRotation(heading)
    m.getElement().classList.toggle('has-heading', heading != null)
  }

  useEffect(() => {
    if (!on) { setFix(null); return }
    if (!('geolocation' in navigator)) { setMessage('This browser can’t show where you are.'); setOn(false); return }
    centred.current = false
    setMessage('Finding where you are…')
    const watch = navigator.geolocation.watchPosition(p => {
      const { heading, speed } = p.coords
      const moving = heading != null && Number.isFinite(heading) && speed != null && speed >= MOVING_MS
      setFix({ lng: p.coords.longitude, lat: p.coords.latitude, accuracy: p.coords.accuracy, heading: moving ? heading : null })
      setMessage('')
    }, err => {
      if (err.code === err.PERMISSION_DENIED) {
        setMessage('Location is off for GameSense. Allow it in your phone’s settings to see where you are.')
        setOn(false)
      } else setMessage('Your phone can’t find where you are right now. Try again in the open.')
    }, { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 })

    // Android sends true-north readings as their own event; iPhone adds a compass
    // heading to the ordinary one. A phone with no compass just sends neither.
    const kind = 'ondeviceorientationabsolute' in window ? 'deviceorientationabsolute' : 'deviceorientation'
    let last = -1
    const onTurn = (e: Event) => {
      const h = compassHeading(e as OrientationEventWithCompass)
      if (h == null) return
      // A couple of degrees of hand shake is not a turn.
      if (last >= 0 && Math.abs(((h - last + 540) % 360) - 180) < 2) return
      last = h; compass.current = h; aim()
    }
    window.addEventListener(kind, onTurn)
    return () => {
      navigator.geolocation.clearWatch(watch)
      window.removeEventListener(kind, onTurn)
      compass.current = null
    }
    // aim reads refs only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    aim()
    setSource(map, 'me', [{ type: 'Feature', properties: {}, geometry: circle([fix.lng, fix.lat], Math.max(5, fix.accuracy)) }])
    if (!centred.current) {
      centred.current = true
      map.easeTo({ center: [fix.lng, fix.lat], zoom: Math.max(map.getZoom(), 15) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, ready, fix])
  useEffect(() => () => { marker.current?.remove(); marker.current = null }, [])

  function toggle() {
    setMessage('')
    // iPhone asks before it shares the compass, and only from inside the tap itself.
    const orientation = window.DeviceOrientationEvent as unknown as OrientationPermission | undefined
    if (!on && typeof orientation?.requestPermission === 'function') orientation.requestPermission().catch(() => 'denied')
    setOn(v => !v)
  }

  return { on, toggle, message, clearMessage: () => setMessage(''), fix }
}
