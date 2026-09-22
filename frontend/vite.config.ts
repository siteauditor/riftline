import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ isSsrBuild }) => ({
  plugins: [react(), tailwindcss()],
  // The server bundle is one file the prerenderer imports; it has no use for
  // a copy of public/ beside it.
  publicDir: isSsrBuild ? false : 'public',
  server: {
    port: 5173,
    // Proxying /api to FastAPI keeps the browser on one origin in development,
    // so CORS never enters the picture while iterating.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
