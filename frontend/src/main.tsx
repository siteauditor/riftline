import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import './index.css'
import App from './App'
import Home from './routes/Home'
import Profile from './routes/Profile'
import Mastery from './routes/Mastery'
import PlayerChampions from './routes/PlayerChampions'
import Tierlist from './routes/Tierlist'
import Draft from './routes/Draft'
import Champion from './routes/Champion'
import LiveGame from './routes/LiveGame'
import Item from './routes/Item'
import Items from './routes/Items'
import Leaderboard from './routes/Leaderboard'
import Match from './routes/Match'
import NotFound, { RouteError } from './routes/NotFound'

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
  ;(window as unknown as { queryClient: QueryClient }).queryClient = queryClient
}

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    // Without this, a crash anywhere below shows React Router's own developer
    // screen, which addresses the visitor as the person who can fix it.
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Home /> },
      { path: 'summoner/:platform/:name/:tag', element: <Profile /> },
      { path: 'summoner/:platform/:name/:tag/champions', element: <PlayerChampions /> },
      { path: 'summoner/:platform/:name/:tag/mastery', element: <Mastery /> },
      { path: 'summoner/:platform/:name/:tag/live', element: <LiveGame /> },
      { path: 'leaderboards', element: <Leaderboard /> },
      { path: 'tierlist', element: <Tierlist /> },
      { path: 'draft', element: <Draft /> },
      { path: 'champions/:championId', element: <Champion /> },
      { path: 'items', element: <Items /> },
      { path: 'items/:itemId', element: <Item /> },
      { path: 'match/:matchId', element: <Match /> },
      // nginx serves index.html for every path it does not recognise, so the
      // router is what decides an address is not a page. Keep this last.
      { path: '*', element: <NotFound /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
