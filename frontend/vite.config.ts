import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiProxy = process.env.VITE_API_PROXY || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: apiProxy, changeOrigin: true },
    },
  },
})
