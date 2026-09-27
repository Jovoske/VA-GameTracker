import { type ReactNode, Suspense, lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { getToken, loginPath } from './api'
import Layout from './components/Layout'
import Admin from './pages/Admin'
import Animals from './pages/Animals'
import Cameras from './pages/Cameras'
import Insights from './pages/Insights'
import Login from './pages/Login'
import Photos from './pages/Photos'
import Tonight from './pages/Tonight'
import SitMode from './pages/SitMode'
import Stands from './pages/Stands'

/**
 * The map engine loads only for the map.
 *
 * maplibre-gl is a megabyte, about four fifths of everything this app shipped,
 * and Map.tsx is the only file that touches it. Every hunter opening Tonight on
 * a phone at the top of a track was paying for a renderer they were not going to
 * look at. Split out, the first load carries the verdict and nothing else, and
 * the map arrives when somebody actually asks for it.
 */
const MapPage = lazy(() => import('./pages/Map'))

/** Signed out, the page asked for is kept for after signing in: an alert's photo
 *  opens once the hunter is back, not Tonight (audit D-10, I-22). */
function RequireAuth({ children }: { children: ReactNode }) {
  const loc = useLocation()
  return getToken() ? <>{children}</> : <Navigate to={loginPath(loc.pathname + loc.search)} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/sit/:sitId"
        element={
          <RequireAuth>
            <SitMode />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Tonight />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/photos" element={<Photos />} />
        <Route path="/stands" element={<Stands />} />
        <Route
          path="/map"
          element={
            // Says which thing is loading. A bare spinner here would be
            // indistinguishable from the map failing to come up at all, which on
            // a slow valley connection is the likelier reading.
            <Suspense fallback={<div style={{ color: 'var(--text-dim)' }}>Loading the map…</div>}>
              <MapPage />
            </Suspense>
          }
        />
        <Route path="/insights" element={<Insights />} />
        <Route path="/animals" element={<Animals />} />
        <Route path="/settings" element={<Admin />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
