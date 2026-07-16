import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend farklı bir portta ise: VITE_API_TARGET=http://localhost:8001 npm run dev
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API_TARGET ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
})
