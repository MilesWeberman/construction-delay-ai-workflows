import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs separately: `uv run delay-ai serve`.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
