import type maplibregl from 'maplibre-gl'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useRefetchOnReturn } from '../hooks'
import { t } from '../i18n'
import { DEFAULT_FILTERS, PARTS, PERIODS, activityPath, drawActivity, type Activity, type ActivityFilters } from './activity'

const KEY = 'gs_map_activity'
const LOAD_TIMEOUT_MS = 30_000
type Failure = Error & { offline?: boolean; timeout?: boolean; status?: number }

// The filters are remembered on this phone: a convenience, so storage may fail.
function readFilters(): ActivityFilters {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (!saved || typeof saved !== 'object') return DEFAULT_FILTERS
    return {
      nights: PERIODS.some(p => p.id === saved.nights) ? saved.nights : DEFAULT_FILTERS.nights,
      part: PARTS.some(p => p.id === saved.part) ? saved.part : DEFAULT_FILTERS.part,
      species: typeof saved.species === 'string' && saved.species ? saved.species : DEFAULT_FILTERS.species,
    }
  } catch { return DEFAULT_FILTERS }
}
function writeFilters(f: ActivityFilters) {
  try { localStorage.setItem(KEY, JSON.stringify(f)) } catch { /* a convenience, never a requirement */ }
}

/**
 * The activity view's data and circles. Loads while `on`, again on every change of
 * filter, and draws nothing (so the normal map is back) once `on` goes false.
 * While a new answer is on its way the old circles stay, so the map never blinks.
 */
export function useActivity(map: maplibregl.Map | null, ready: boolean, on: boolean) {
  const [filters, setFiltersState] = useState<ActivityFilters>(readFilters)
  const [data, setData] = useState<Activity | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [picked, setPicked] = useState<string | null>(null)
  const request = useRef(0)

  const load = useCallback(async () => {
    const id = ++request.current
    setLoading(true); setErr('')
    try {
      const next = await api<Activity>(activityPath(filters), { timeoutMs: LOAD_TIMEOUT_MS })
      if (id === request.current) setData(next)
    } catch (e) {
      if (id !== request.current) return
      const x = e as Failure
      // A species that has since been hidden: back to every animal.
      if (x.status === 404 && filters.species !== 'all') { setFilters({ ...filters, species: 'all' }); return }
      setErr(x.offline ? t('activity.noSignal') : x.timeout ? t('activity.noAnswer') : t('activity.couldnt', { why: x.message }))
    } finally { if (id === request.current) setLoading(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])
  useEffect(() => { if (on) load(); else { request.current++; setLoading(false); setErr(''); setPicked(null) } }, [on, load])
  useRefetchOnReturn(() => { if (on) load() }, 120_000)

  // The source is only touched once there is something to draw or take away: an
  // empty update at start-up is still work for the map, and moves its 'idle' event.
  const drawn = useRef(false)
  useEffect(() => {
    if (!map || !ready) return
    if (on && data) { drawActivity(map, data, picked); drawn.current = true }
    else if (drawn.current) { drawActivity(map, null, null); drawn.current = false }
  }, [map, ready, on, data, picked])

  function setFilters(next: ActivityFilters) { setFiltersState(next); writeFilters(next) }
  const pickedCamera = picked ? data?.cameras.find(c => c.camera_id === picked) ?? null : null
  return { filters, setFilters, data, loading, err, reload: load, picked: pickedCamera, pick: setPicked }
}
