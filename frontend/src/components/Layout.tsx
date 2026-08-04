import { useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { setToken } from '../api'

const TABS = [
  { to: '/', label: 'Tonight', ico: '🌙', end: true },
  { to: '/cameras', label: 'Cameras', ico: '📷' },
  { to: '/map', label: 'Map', ico: '🗺️' },
  { to: '/insights', label: 'Insights', ico: '📈' },
  { to: '/animals', label: 'Animals', ico: '🦌' },
  { to: '/settings', label: 'Settings', ico: '⚙️' },
]

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
  const loc = useLocation()

  // Browser-tab / app-switcher title follows the page.
  useEffect(() => {
    const t = TABS.find((x) => (x.end ? loc.pathname === '/' : loc.pathname.startsWith(x.to)))
    document.title = t ? `GameSense · ${t.label}` : 'GameSense'
  }, [loc.pathname])

  function logout() {
    setToken(null)
    nav('/login')
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', minHeight: '100%' }}>
      <header className="appbar">
        <div style={{ fontWeight: 700, fontSize: 16, marginRight: 6, whiteSpace: 'nowrap' }}>
          Game<span style={{ color: 'var(--go)' }}>Sense</span>
        </div>

        {/* Desktop / tablet: links in the header. On phones the bottom tab bar takes over. */}
        <nav className="topnav">
          {TABS.map((t) => (
            <NavLink key={t.to} to={t.to} end={t.end} style={({ isActive }) => linkStyle(isActive)}>
              {t.label}
            </NavLink>
          ))}
        </nav>

        <button
          onClick={logout}
          className="signout"
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: '1px solid var(--border)',
            color: 'var(--text-dim)',
            borderRadius: 8,
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: 13,
            whiteSpace: 'nowrap',
          }}
        >
          Sign out
        </button>
      </header>

      <main className="page" style={{ padding: 16 }}>
        <Outlet />
      </main>

      {/* Phone: thumb-reachable bottom tabs (iOS-app style, matches the PWA delivery). */}
      <nav className="tabbar">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => (isActive ? 'active' : '')}>
            <span className="ico" aria-hidden="true">{t.ico}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
