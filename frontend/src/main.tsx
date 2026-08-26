import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
// The typeface, actually shipped. theme.css used to name Inter and then never
// load it, so every phone quietly rendered its own system sans and the app had
// no lettering of its own at all. Weight axis only, and unicode-range keeps a
// Spanish estate from ever downloading the Cyrillic subset.
import '@fontsource-variable/ibm-plex-sans/wght.css'
import App from './App'
import './theme.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
