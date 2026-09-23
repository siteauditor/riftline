import { defineConfig, devices } from '@playwright/test'

/**
 * The browser smoke test, against a served build.
 *
 * Not against the dev server: the point is the site as nginx serves it,
 * prerendered pages hydrating in a real browser. Serve one first, locally
 * with `node prerender/serve.mjs --pages <pages>/local --api <api>`, and in
 * CI the same server in a container over the pages the prerender job wrote.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:6123',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
