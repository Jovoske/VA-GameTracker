import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { getToken } from './api'
import Layout from './components/Layout'
import Admin from './pages/Admin'
import Animals from './pages/Animals'
import Cameras from './pages/Cameras'
import Insights from './pages/Insights'
import Login from './pages/Login'
import MapPage from './pages/Map'
import Tonight from './pages/Tonight'

function RequireAuth({ children }: { children: ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Tonight />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/map" element={<MapPage />} />
        <Route path="/insights" element={<Insights />} />
        <Route path="/animals" element={<Animals />} />
        <Route path="/settings" element={<Admin />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
