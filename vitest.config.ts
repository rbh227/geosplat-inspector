import path from 'path'
import { defineConfig } from 'vitest/config'

// jsdom gives `window.location` for the WS-URL helper; the rest are pure.
export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@agent': path.resolve(__dirname, './frontend/src/agent/index.ts'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'frontend/src/**/*.test.ts'],
  },
})
