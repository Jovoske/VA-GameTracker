import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { setToken } from '../api'

const linkStyle = (isActive: boolean) => ({
  padding: '8px 12px',
  borderRadius: 8,
  fontSize: 14,
  color: isActive ? 'var(--text)' : 'var(--text-dim)',
  background: isActive ? 'var(--surface-2)' : 'transparent',
  fontWeight: isActive ? 600 : 400,
})

export default function Layout() {
  const nav = useNavigate()

  function logout() {
    setToken(null)
    nav('/login')
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', minHeight: '100%' }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '12px 16px',
          borderBottom: '1px solid var(--border)',
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 16, marginRight: 6 }}>
          Game<span style={{ color: 'var(--go)' }}>Sense</span>
        </div>
        <NavLink to="/" end style={({ isActive }) => linkStyle(isActive)}>
          Tonight
        </NavLink>
        <NavLink to="/cameras" style={({ isActive }) => linkStyle(isActive)}>
          Cameras
        </NavLink>
        <NavLink to="/map" style={({ isActive }) => linkStyle(isActive)}>
          Map
        </NavLink>
        <NavLink to="/insights" style={({ isActive }) => linkStyle(isActive)}>
          Insights
        </NavLink>
        <NavLink to="/settings" style={({ isActive }) => ({ ...linkStyle(isActive), marginLeft: 'auto' })}>
          Settings
        </NavLink>
        <button
          onClick={logout}
          style={{
            background: 'none',
            border: '1px solid var(--border)',
            color: 'var(--text-dim)',
            borderRadius: 8,
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          Sign out
        </button>
      </header>
      <main style={{ padding: 16 }}>
        <Outlet />
      </main>
    </div>
  )
}
