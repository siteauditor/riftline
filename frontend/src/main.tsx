import { StrictMode } from 'react'
import { createRoot, hydrateRoot } from 'react-dom/client'
import {
  HydrationBoundary,
  QueryClient,
  QueryClientProvider,
  type DehydratedState,
} from '@tanstack/react-query'
import { createBrowserRouter, matchRoutes, RouterProvider } from 'react-router-dom'

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

/**
 * The route modules the first location needs, loaded before anything renders.
 *
 * Pages are code-split (routes.tsx), and a data router renders nothing until
 * a lazy route has loaded. On a prerendered page that nothing would be
 * hydrated against a full document: React would discard the HTML and render
 * from scratch, and the point of prerendering would be lost. So the matched
 * modules are imported first and the router starts already initialised. On
 * the shell it costs nothing extra: the chunk had to load anyway.
 */
async function loadRoutesFor(location: Location): Promise<void> {
  const matches = matchRoutes(routes, location) ?? []
  await Promise.all(
    matches.map(async ({ route }) => {
      if (typeof route.lazy !== 'function') return
      Object.assign(route, await route.lazy())
      route.lazy = undefined
    }),
  )
}

const container = document.getElementById('root')!

// A chunk that will not load, most often because a deploy replaced the
// hashed files under a tab that was open. Once, a reload picks up the new
// build; a second failure in the same session is something else, and the
// page says so rather than staying blank.
const RELOADED = 'riftline:reloaded-for-chunk'
function chunkFailed(): void {
  let reloaded = false
  try {
    reloaded = sessionStorage.getItem(RELOADED) === '1'
    if (!reloaded) sessionStorage.setItem(RELOADED, '1')
  } catch {
    // Storage refused: fall through to the message.
  }
  if (!reloaded) {
    window.location.reload()
    return
  }
  container.innerHTML =
    '<div style="max-width:36rem;margin:4rem auto;padding:0 1rem;font-family:Barlow,system-ui,sans-serif;color:#a1aec2">' +
    '<h1 style="color:#eef3fa;font-size:1.25rem">This page could not load</h1>' +
    '<p>Part of the app failed to download. Check the connection and reload the page.</p></div>'
}
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  chunkFailed()
})

loadRoutesFor(window.location).catch(chunkFailed).then(() => {
  const router = createBrowserRouter(routes)
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
})
