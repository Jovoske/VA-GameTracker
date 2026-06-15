import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
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
