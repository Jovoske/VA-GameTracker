import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { setToken } from '../api'

/**
 * Bottom navigation.
 *
 * This was a desktop top bar: six links plus a Sign-out button, roughly 635px of
 * content in a 390px viewport with no wrap, at ~33px tall. Half of it sat off the
 * right edge of the phone and none of it was reachable one-handed — which matters
 * for an app whose user has a rifle or binoculars in the other hand.
 *
 * Three tabs, 56px, in the thumb zone, with a safe-area inset so the last row is
 * not under the home indicator. Secondary destinations (Insights, Map, Settings)
 * live in the header, which is where infrequent things belong.
 */

const TABS = [
  { to: '/', label: 'Tonight', end: true },
  { to: '/stands', label: 'Stands', end: false },
  { to: '/cameras', label: 'Cameras', end: false },
]

const SECONDARY = [
  { to: '/insights', label: 'Insights' },
  { to: '/map', label: 'Map' },
  { to: '/settings', label: 'Settings' },
]

const tabStyle = (isActive: boolean) => ({
  flex: 1,
  minHeight: 56,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: 13,
  fontWeight: isActive ? 700 : 500,
  color: isActive ? 'var(--text)' : 'var(--text-dim)',
  borderTop: `2px solid ${isActive ? 'var(--v-best)' : 'transparent'}`,
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
          gap: 10,
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ fontWeight: 700, fontSize: 16, marginRight: 'auto' }}>
          Game<span style={{ color: 'var(--v-best)' }}>Sense</span>
        </div>
        {SECONDARY.map((s) => (
          <NavLink
            key={s.to}
            to={s.to}
            style={({ isActive }) => ({
              fontSize: 13,
              padding: '8px 6px',
              color: isActive ? 'var(--text)' : 'var(--text-dim)',
              fontWeight: isActive ? 600 : 400,
            })}
          >
            {s.label}
          </NavLink>
        ))}
        <button
          onClick={logout}
          style={{
            background: 'none',
            border: '1px solid var(--border)',
            color: 'var(--text-dim)',
            borderRadius: 8,
            padding: '8px 10px',
            cursor: 'pointer',
            fontSize: 12,
          }}
        >
          Sign out
        </button>
      </header>

      {/* Bottom padding clears the fixed nav so the last card is never trapped
          underneath it. */}
      <main style={{ padding: 16, paddingBottom: 'calc(72px + env(safe-area-inset-bottom))' }}>
        <Outlet />
      </main>

      <nav
        style={{
          position: 'fixed',
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          background: 'var(--surface)',
          borderTop: '1px solid var(--border)',
          paddingBottom: 'env(safe-area-inset-bottom)',
          zIndex: 40,
        }}
      >
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end} style={({ isActive }) => tabStyle(isActive)}>
            {t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
