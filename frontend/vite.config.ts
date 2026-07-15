import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  define: {
    'import.meta.env.VITE_SSE_ENABLED': JSON.stringify(process.env.VITE_SSE_ENABLED ?? 'true'),
    'import.meta.env.VITE_POLL_MS': JSON.stringify(process.env.VITE_POLL_MS ?? '500'),
    'import.meta.env.VITE_SSE_THROTTLE_MS': JSON.stringify(process.env.VITE_SSE_THROTTLE_MS ?? '50'),
    'import.meta.env.VITE_STREAM_BASE_URL': JSON.stringify(process.env.VITE_STREAM_BASE_URL ?? ''),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
