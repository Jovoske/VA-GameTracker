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

const LANGS = ['en', 'fi', 'sv', 'nb', 'es'] as const

// The app's own dictionaries, for the few words said before its code is running: the
// service worker's "no signal, nothing saved" answer, the page's "taking a long time
// to open", the install description. Read when the build needs them, not imported
// here: a config that imports them restarts the dev server on every change to a
// translation.
function words(keys: string[]): Record<string, Record<string, string>> {
  const dir = fileURLToPath(new URL('./src/i18n/', import.meta.url))
  return Object.fromEntries(LANGS.map((lang) => {
    const out = buildSync({ entryPoints: [path.join(dir, `${lang}.ts`)], bundle: true, write: false, format: 'cjs', platform: 'node', logLevel: 'silent' })
    const mod: { exports: { default?: Record<string, unknown> } } = { exports: {} }
    new Function('module', 'exports', out.outputFiles[0].text)(mod, mod.exports)
    return [lang, Object.fromEntries(keys.map((key) => {
      const text = mod.exports.default?.[key]
      if (typeof text !== 'string') throw new Error(`src/i18n/${lang}.ts has no ${key}`)
      return [key, text]
    }))]
  }))
}

// What the service worker says itself, in every language.
function swText(): Record<string, { offline: string }> {
  const all = words(['sw.offline'])
  return Object.fromEntries(LANGS.map((lang) => [lang, { offline: all[lang]['sw.offline'] }]))
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

const BOOT_TEXT_DEFAULT = '/*__GS_BOOT__*/null'

/**
 * The page's own words for when the app's code never arrives (no signal on a first
 * launch, or a deploy removed the files an old copy names), in every language: the
 * phone's saved language picks them (index.html). And, in a build, the install
 * description in each language beside the English manifest, which the page names
 * instead when the phone speaks another.
 */
function stampBootText(): Plugin {
  let building = false
  return {
    name: 'gamesense-stamp-boot',
    configResolved(config) { building = config.command === 'build' },
    transformIndexHtml(html) {
      if (!html.includes(BOOT_TEXT_DEFAULT)) throw new Error('index.html has no __GS_BOOT__ marker for its words')
      const all = words(['boot.slow', 'boot.why', 'common.reload'])
      const text = Object.fromEntries(LANGS.map((lang) => [lang, {
        slow: all[lang]['boot.slow'], why: all[lang]['boot.why'], reload: all[lang]['common.reload'],
        manifest: building && lang !== 'en' ? `/manifest.${lang}.webmanifest` : null,
      }]))
      // Inside a <script>: nothing in the words may close it.
      return html.replace(BOOT_TEXT_DEFAULT, JSON.stringify(text).replace(/</g, '\\u003c'))
    },
    writeBundle(options) {
      const out = options.dir || 'dist'
      const manifest = JSON.parse(fs.readFileSync(path.join(out, 'manifest.webmanifest'), 'utf8'))
      const all = words(['app.description'])
      for (const lang of LANGS) {
        const file = path.join(out, lang === 'en' ? 'manifest.webmanifest' : `manifest.${lang}.webmanifest`)
        fs.writeFileSync(file, JSON.stringify({ ...manifest, lang, description: all[lang]['app.description'] }, null, 2) + '\n')
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), stampServiceWorker(), stampBootText()],
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
