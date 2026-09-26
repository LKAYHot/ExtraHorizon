import http from 'node:http'
import { sveltekit } from '@sveltejs/kit/vite'
import { defineConfig } from 'vite'

// Dev: the Vite server proxies /api (HTTP + the vision WebSocket) to the local backend.
// Keep-alive agent: without it http-proxy sends every request with "Connection: close"
// and on Windows intermittently hits ECONNRESET (same fix as in AzIAIBetter's UI).
const agent = new http.Agent({ keepAlive: true })
const target = process.env.EH_BACKEND ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target, ws: true, agent },
    },
  },
  build: { target: 'es2022', sourcemap: false },
  test: { include: ['src/**/*.test.js'], environment: 'node' },
})
