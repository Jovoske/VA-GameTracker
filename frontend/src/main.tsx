import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
// The typeface, actually shipped. theme.css used to name Inter and then never
// load it, so every phone quietly rendered its own system sans and the app had
// no lettering of its own at all. Weight axis only, and unicode-range keeps a
// Spanish estate from ever downloading the Cyrillic subset.
import '@fontsource-variable/ibm-plex-sans/wght.css'
import App from './App'
import './theme.css'

// A data router, so a page can hold back a navigation it would lose work to: the
// map asks before Back or a tab throws away an unsaved outline (useBlocker needs
// this kind of router). Every route still lives in App's <Routes>.
const router = createBrowserRouter([{ path: '*', element: <App /> }])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
