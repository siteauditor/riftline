import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import {
  HydrationBoundary,
  QueryClient,
  QueryClientProvider,
  type DehydratedState,
} from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import './index.css'
import { routes } from './routes'

declare global {
  interface Window {
    /** React Query's cache as the prerenderer left it, on a prerendered page. */
    __RQ_STATE__?: DehydratedState
    queryClient?: QueryClient
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Riot data is already cached server-side against the rate limit, so the
      // client caches generously and never refetches on window focus: an
      // accidental tab switch should not spend somebody's request budget.
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Retrying a 404 or a rate limit only makes both worse.
        const kind = (error as { kind?: string })?.kind
        // 'unavailable' and 'gone' are settled answers about the endpoint
        // itself, so retrying spends the rate limit to be told the same thing.
        if (
          kind === 'not_found' ||
          kind === 'rate_limited' ||
          kind === 'expired_key' ||
          kind === 'unavailable' ||
          kind === 'gone'
        ) {
          return false
        }
        return failureCount < 2
      },
    },
  },
})

// The live game page is the one page that cannot be reached on demand: 31
// production lookups on 2026-09-21 found nobody in a game. So in development
// the cache is reachable from outside, and the screenshot script can seed a
// lobby, a champion select or an ended game and photograph it. Stripped from
// the production bundle by the `import.meta.env.DEV` branch.
if (import.meta.env.DEV) {
  window.queryClient = queryClient
}

const router = createBrowserRouter(routes)
const container = document.getElementById('root')!

const app = (
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <HydrationBoundary state={window.__RQ_STATE__}>
        <RouterProvider router={router} />
      </HydrationBoundary>
    </QueryClientProvider>
  </StrictMode>
)

// A prerendered page arrives with its markup already in #root, and the
// numbers it was rendered from in __RQ_STATE__: React takes over what is
// there. The shell arrives with nothing but a comment, and is rendered into.
if (container.firstElementChild) {
  hydrateRoot(container, app)
} else {
  createRoot(container).render(app)
}
