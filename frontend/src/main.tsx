import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
// The typeface, actually shipped. theme.css used to name Inter and then never
// load it, so every phone quietly rendered its own system sans and the app had
// no lettering of its own at all. Weight axis only, and unicode-range keeps a
// Spanish estate from ever downloading the Cyrillic subset.
import '@fontsource-variable/ibm-plex-sans/wght.css'
import App from './App'
import { RouteCrash } from './components/ErrorBoundary'
import { installCrashReporting } from './crash'
import { registerServiceWorker } from './serviceWorker'
import './theme.css'

// First, so a crash while the app starts is reported too.
installCrashReporting()

// A data router, so a page can hold back a navigation it would lose work to: the
// map asks before Back or a tab throws away an unsaved outline (useBlocker needs
// this kind of router). Every route still lives in App's <Routes>. A crash outside
// a page (the frame, sign-in, Sit mode) lands on RouteCrash, never a blank screen.
const router = createBrowserRouter([{ path: '*', element: <App />, errorElement: <RouteCrash /> }])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)

registerServiceWorker()
