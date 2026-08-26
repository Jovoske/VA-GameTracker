import type { Icon } from '@phosphor-icons/react'
import { CameraIcon } from '@phosphor-icons/react/dist/csr/Camera'
import { ChartLineUpIcon } from '@phosphor-icons/react/dist/csr/ChartLineUp'
import { CrosshairIcon } from '@phosphor-icons/react/dist/csr/Crosshair'
import { MapTrifoldIcon } from '@phosphor-icons/react/dist/csr/MapTrifold'
import { MoonStarsIcon } from '@phosphor-icons/react/dist/csr/MoonStars'
import { PawPrintIcon } from '@phosphor-icons/react/dist/csr/PawPrint'
import { SlidersHorizontalIcon } from '@phosphor-icons/react/dist/csr/SlidersHorizontal'
import { useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { setToken } from '../api'

/**
 * Icons are drawn, from one family, at one weight.
 *
 * These were emoji: 🌙 🎯 📷 🗺️ 📈 🦌 ⚙️. Emoji are not an icon system. They
 * render as a different picture on every phone, they carry another vendor's
 * colour palette into the middle of this one, and they sit on their own baseline
 * so no two ever align. Phosphor at one size, regular when the tab is idle and
 * filled when it is current, which is the weight change a native tab bar uses to
 * say "you are here" without needing the colour to do all the work.
 *
 * Deep imports rather than the barrel: the package carries about nine thousand
 * icons and this app wants seven of them.
 */
const TABS: { to: string; label: string; Ico: Icon; end?: boolean }[] = [
  { to: '/', label: 'Tonight', Ico: MoonStarsIcon, end: true },
  { to: '/stands', label: 'Stands', Ico: CrosshairIcon },
  { to: '/cameras', label: 'Cameras', Ico: CameraIcon },
  { to: '/map', label: 'Map', Ico: MapTrifoldIcon },
  { to: '/insights', label: 'Insights', Ico: ChartLineUpIcon },
  { to: '/animals', label: 'Animals', Ico: PawPrintIcon },
  { to: '/settings', label: 'Settings', Ico: SlidersHorizontalIcon },
]

const linkStyle = (isActive: boolean) => ({
  padding: '7px 11px',
  borderRadius: 'var(--r-ctl)',
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
        <div style={{ fontWeight: 600, fontSize: 16, marginRight: 6, whiteSpace: 'nowrap', letterSpacing: '-0.02em' }}>
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
            borderRadius: 'var(--r-ctl)',
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: 13,
            whiteSpace: 'nowrap',
          }}
        >
          Sign out
        </button>
      </header>

      {/* Padding lives in theme.css — an inline padding here overrides the
          media-query rule that clears the bottom tab bar, hiding content under it. */}
      <main className="page">
        <Outlet />
      </main>

      {/* Phone: thumb-reachable bottom tabs (iOS-app style, matches the PWA delivery). */}
      <nav className="tabbar">
        {TABS.map(({ to, label, Ico, end }) => (
          <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? 'active' : '')}>
            {({ isActive }) => (
              <>
                <span className="ico">
                  <Ico size={22} weight={isActive ? 'fill' : 'regular'} />
                </span>
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
