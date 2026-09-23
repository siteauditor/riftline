/// <reference types="vitest/config" />
import path from 'node:path'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ isSsrBuild }) => ({
  plugins: [
    // The React Compiler memoises components and hooks on its own, so new
    // code never needs useMemo or useCallback by hand. It skips, silently, a
    // component that breaks the rules of hooks; the lint rule catches those.
    react({ compiler: true }),
    tailwindcss(),
  ],
  // The server bundle is one file the prerenderer imports; it has no use for
  // a copy of public/ beside it.
  publicDir: isSsrBuild ? false : 'public',
  // `@/` is src/, the alias the shadcn/ui components are written against.
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
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
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
}))
