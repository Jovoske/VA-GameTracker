import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildSync } from 'esbuild'
import { defineConfig, type Plugin } from 'vite'

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:8000'

// One id per build, shared by the app (crash reports, "a new version is ready") and
// its service worker. A new id is what makes a phone install the new worker.
const BUILD = process.env.GS_BUILD || new Date().toISOString().replace(/\D/g, '').slice(0, 14)

// What the service worker says itself (its "no signal, nothing saved" answer), in
// every language, from the app's own dictionaries. Read when the build writes sw.js,
// not imported here: a config that imports them restarts the dev server on every
// change to a translation.
function swText(): Record<string, { offline: string }> {
  const dir = fileURLToPath(new URL('./src/i18n/', import.meta.url))
  return Object.fromEntries(['en', 'fi', 'sv', 'nb', 'es'].map((lang) => {
    const out = buildSync({ entryPoints: [path.join(dir, `${lang}.ts`)], bundle: true, write: false, format: 'cjs', platform: 'node', logLevel: 'silent' })
    const mod: { exports: { default?: Record<string, unknown> } } = { exports: {} }
    new Function('module', 'exports', out.outputFiles[0].text)(mod, mod.exports)
    const offline = mod.exports.default?.['sw.offline']
    if (typeof offline !== 'string') throw new Error(`src/i18n/${lang}.ts has no sw.offline`)
    return [lang, { offline }]
  }))
}
const SW_TEXT_DEFAULT = "/*__GS_TEXT__*/{ en: { offline: 'Offline, and nothing cached for this yet.' } }"

/**
 * Stamps dist/sw.js with this build's id and the files it must store at install.
 *
 * Without the list the worker only kept what happened to pass through it, which on
 * a first visit was nothing: the next launch with no signal had no code (audit
 * K-03). Without the id, sw.js was the same bytes on every deploy, so a phone never
 * installed a new worker and never let go of old files (D-20). Only the Latin font
 * cuts are listed: a Spanish estate never asks for Cyrillic.
 */
function stampServiceWorker(): Plugin {
  return {
    name: 'gamesense-stamp-sw',
    apply: 'build',
    writeBundle(options, bundle) {
      const out = options.dir || 'dist'
      const assets = Object.keys(bundle)
        .filter((f) => f.startsWith('assets/'))
        .filter((f) => /\.(js|css)$/.test(f) || (/\.woff2$/.test(f) && /latin/.test(f)))
        .map((f) => '/' + f)
        .sort()
      const file = path.join(out, 'sw.js')
      const src = fs.readFileSync(file, 'utf8')
      const stamped = src
        .replace("'__GS_BUILD__'", JSON.stringify(BUILD))
        .replace('/*__GS_ASSETS__*/[]', JSON.stringify(assets))
        .replace(SW_TEXT_DEFAULT, JSON.stringify(swText()))
      if (stamped === src || !stamped.includes(JSON.stringify(BUILD)) || stamped.includes('__GS_TEXT__')) {
        throw new Error('sw.js was not stamped: its __GS_BUILD__ / __GS_ASSETS__ / __GS_TEXT__ markers are missing')
      }
      fs.writeFileSync(file, stamped)
    },
  }
}

export default defineConfig({
  plugins: [react(), stampServiceWorker()],
  define: { __GS_BUILD__: JSON.stringify(BUILD) },
  server: {
    host: true,
    port: 5173,
    // Accept any Host header so the app is reachable over a tunnel / LAN IP, not just
    // localhost (Vite otherwise blocks unknown hosts as DNS-rebinding protection).
    allowedHosts: true,
    // Polling is required for Vite's file watcher to see edits across a
    // Windows -> Docker bind mount (native fs events don't cross it).
    watch: { usePolling: true, interval: 300 },
    proxy: {
      '/api': { target: apiProxy, changeOrigin: true },
    },
  },
})
