import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Backend the dev server proxies to. Override with VITE_BACKEND_URL.
const BACKEND_PROXY_TARGET = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@agent': path.resolve(__dirname, './frontend/src/agent/index.ts'),
    },
  },
  server: {
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    // Same-origin proxy to the backend so the renderer loads scenes and opens
    // the agent WS without tripping COEP `require-corp` / CORS / canvas taint.
    proxy: {
      '/scene': BACKEND_PROXY_TARGET,
      '/metrics': BACKEND_PROXY_TARGET,
      '/edit': BACKEND_PROXY_TARGET,
      '/undo': BACKEND_PROXY_TARGET,
      '/redo': BACKEND_PROXY_TARGET,
      '/agent': BACKEND_PROXY_TARGET,
      '/health': BACKEND_PROXY_TARGET,
      '/ws': { target: BACKEND_PROXY_TARGET.replace(/^http/, 'ws'), ws: true },
    },
  },
  optimizeDeps: {
    exclude: ['@sparkjsdev/spark'],
  },
})
