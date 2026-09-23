import type { ComponentType } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { RouteObject } from 'react-router-dom'

import App from './App'
import { sliceFromParams } from './lib/searchParams'
import { CHAMPION_MIN_GAMES, DEFAULT_LADDER, queries, TIERLIST_MIN_GAMES } from './lib/queries'
import NotFound, { RouteError } from './routes/NotFound'

/**
 * The route table, shared by the browser and the prerenderer.
 *
 * Each route that is prerendered carries a `prefetch` in its handle: the
 * queries the page reads, fetched into a QueryClient before the page renders
 * on the server, so the HTML has its numbers and the browser hydrates from
 * the same cache instead of fetching again. The keys come from `queries`, the
 * same definitions the components use, so the two cannot drift.
 *
 * One chunk per page. Every page is `lazy`, so the first load carries the
 * shell and the one page asked for rather than all sixteen. The browser
 * entry (main.tsx) loads the chunks the first location matches before it
 * hydrates, and the prerenderer's static handler loads them inside `query`,
 * so neither side ever renders a route without its component. `handle`
 * stays here rather than in the lazy module: the prefetch runs before the
 * page renders and must not wait on a second import to be found.
 */

export interface PrefetchContext {
  params: Record<string, string | undefined>
  search: URLSearchParams
  queryClient: QueryClient
}

export type Prefetch = (ctx: PrefetchContext) => Promise<unknown>

export interface RouteHandle {
  prefetch?: Prefetch
}

const handle = (prefetch: Prefetch): RouteHandle => ({ prefetch })

const page = (load: () => Promise<{ default: ComponentType }>) => async () => ({
  Component: (await load()).default,
})

const prefetchMethod: Prefetch = ({ queryClient }) => queryClient.prefetchQuery(queries.method())

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <App />,
    // Without this, a crash anywhere below shows React Router's own developer
    // screen, which addresses the visitor as the person who can fix it.
    errorElement: <RouteError />,
    children: [
      {
        index: true,
        lazy: page(() => import('./routes/Home')),
        handle: handle(({ queryClient }) =>
          Promise.all([
            queryClient.prefetchQuery(queries.meta({ minGames: 40 })),
            queryClient.prefetchQuery(queries.corpus()),
            queryClient.prefetchQuery(queries.bestGames()),
            queryClient.prefetchQuery(queries.champions()),
            queryClient.prefetchQuery(queries.topSkins()),
          ]),
        ),
      },
      {
        path: 'summoner/:platform/:name/:tag',
        lazy: page(() => import('./routes/Profile')),
        // From storage only: the manifest lists a profile once the player has
        // enough scored games, and rendering a thousand of them must not cost
        // a Riot call. The page shows these until its live queries answer.
        handle: handle(({ params, queryClient }) => {
          const { platform = '', name = '', tag = '' } = params
          return Promise.all([
            queryClient.prefetchQuery(queries.profileStored(platform, name, tag)),
            queryClient.prefetchQuery(queries.matchesStored(platform, name, tag)),
            queryClient.prefetchQuery(queries.analyticsStored(platform, name, tag)),
          ])
        }),
      },
      {
        path: 'summoner/:platform/:name/:tag/champions',
        lazy: page(() => import('./routes/PlayerChampions')),
      },
      { path: 'summoner/:platform/:name/:tag/mastery', lazy: page(() => import('./routes/Mastery')) },
      { path: 'summoner/:platform/:name/:tag/live', lazy: page(() => import('./routes/LiveGame')) },
      {
        path: 'leaderboards',
        lazy: page(() => import('./routes/Leaderboard')),
        handle: handle(({ queryClient }) =>
          Promise.all([
            queryClient.prefetchQuery(queries.leaderboardSlices()),
            queryClient.prefetchQuery(queries.leaderboard(DEFAULT_LADDER.platform, DEFAULT_LADDER)),
          ]),
        ),
      },
      {
        path: 'tierlist',
        lazy: page(() => import('./routes/Tierlist')),
        handle: handle(({ search, queryClient }) => {
          // The same slice the page builds from an empty query string.
          const slice = { ...sliceFromParams(search, TIERLIST_MIN_GAMES), bracket: null }
          return Promise.all([
            queryClient.prefetchQuery(queries.corpus()),
            queryClient.prefetchQuery(queries.meta(slice)),
          ])
        }),
      },
      {
        path: 'draft',
        lazy: page(() => import('./routes/Draft')),
        handle: handle(({ queryClient }) =>
          Promise.all([
            queryClient.prefetchQuery(queries.champions()),
            queryClient.prefetchQuery(queries.corpus()),
          ]),
        ),
      },
      {
        path: 'champions/:championId',
        lazy: page(() => import('./routes/Champion')),
        handle: handle(({ params, search, queryClient }) => {
          const ref = params.championId ?? ''
          const slice = sliceFromParams(search, CHAMPION_MIN_GAMES)
          return Promise.all([
            queryClient.prefetchQuery(queries.champion(ref, slice)),
            queryClient.prefetchQuery(queries.championProfile(ref)),
          ])
        }),
      },
      {
        path: 'items',
        lazy: page(() => import('./routes/Items')),
        handle: handle(({ queryClient }) => queryClient.prefetchQuery(queries.items())),
      },
      {
        path: 'items/:itemId',
        lazy: page(() => import('./routes/Item')),
        handle: handle(({ params, search, queryClient }) => {
          const { patch, queueId, bracket } = sliceFromParams(search, 1)
          return queryClient.prefetchQuery(queries.item(params.itemId ?? '', { patch, queueId, bracket }))
        }),
      },
      { path: 'match/:matchId', lazy: page(() => import('./routes/Match')) },
      { path: 'method', lazy: page(() => import('./routes/Method')), handle: handle(prefetchMethod) },
      { path: 'method/score', lazy: page(() => import('./routes/method/Score')), handle: handle(prefetchMethod) },
      {
        path: 'method/win-chance',
        lazy: page(() => import('./routes/method/WinChance')),
        handle: handle(prefetchMethod),
      },
      {
        path: 'method/death-review',
        lazy: page(() => import('./routes/method/DeathReview')),
        handle: handle(prefetchMethod),
      },
      {
        path: 'method/lane-labels',
        lazy: page(() => import('./routes/method/LaneLabels')),
        handle: handle(prefetchMethod),
      },
      { path: 'groups', lazy: page(() => import('./routes/Groups')) },
      { path: 'g/:slug', lazy: page(() => import('./routes/Group')) },
      // nginx serves the shell for every path it does not recognise, so the
      // router is what decides an address is not a page. Keep this last.
      { path: '*', element: <NotFound /> },
    ],
  },
]
