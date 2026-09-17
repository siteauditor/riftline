import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import './index.css'
import App from './App'
import Home from './routes/Home'
import Profile from './routes/Profile'
import Mastery from './routes/Mastery'
import Tierlist from './routes/Tierlist'
import Draft from './routes/Draft'
import Champion from './routes/Champion'
import LiveGame from './routes/LiveGame'
import Leaderboard from './routes/Leaderboard'

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

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Home /> },
      { path: 'summoner/:platform/:name/:tag', element: <Profile /> },
      { path: 'summoner/:platform/:name/:tag/mastery', element: <Mastery /> },
      { path: 'summoner/:platform/:name/:tag/live', element: <LiveGame /> },
      { path: 'leaderboards', element: <Leaderboard /> },
      { path: 'tierlist', element: <Tierlist /> },
      { path: 'draft', element: <Draft /> },
      { path: 'champions/:championId', element: <Champion /> },
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
