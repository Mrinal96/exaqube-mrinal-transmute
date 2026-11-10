import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, '.', 'VITE_').VITE_API_PROXY_TARGET ?? 'http://localhost:8000'
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      proxy: { '/api': { target: apiTarget, changeOrigin: true }, '/health': { target: apiTarget, changeOrigin: true } },
    },
  }
})

