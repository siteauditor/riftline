import type { ComponentType } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type { RouteObject } from 'react-router-dom'

import App from './App'
import { positionFromRole, sliceFromParams } from './lib/searchParams'
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
  /**
   * Rendered on request by prerender/live.mjs rather than into a file: a
   * route may then also ask for what Riot says now. The renderer bounds how
   * long that may take; a live query that failed is dropped before the page
   * renders, so the page falls back to exactly what the file would hold.
   */
  live?: boolean
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

// The slice the page builds on its first render: the role from the path, and
// the query string empty, as the page reads it while it hydrates.
const prefetchChampion: Prefetch = ({ params, search, queryClient }) => {
  const ref = params.championId ?? ''
  const slice = { ...sliceFromParams(search, CHAMPION_MIN_GAMES), position: positionFromRole(params.role) }
  return Promise.all([
    queryClient.prefetchQuery(queries.champion(ref, slice)),
    queryClient.prefetchQuery(queries.championProfile(ref)),
  ])
}

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
        // From storage only in the file: the manifest lists a profile once the
        // player has enough scored games, and rendering a thousand of them
        // must not cost a Riot call. The page shows these until its live
        // queries answer.
        //
        // Rendered live, the header also asks for the live profile, so the
        // title and description a crawler or a link preview reads carry the
        // current rank: a file said Bronze I for a day after the player had
        // reached Silver IV (Veystrix#999, 2026-09-23), because a stored rank
        // moves only when someone opens the page. Only the header: the games
        // and analytics describe stored matches either way.
        handle: handle(async ({ params, queryClient, live }) => {
          const { platform = '', name = '', tag = '' } = params
          const current = queries.profile(platform, name, tag)
          await Promise.all([
            queryClient.prefetchQuery(queries.profileStored(platform, name, tag)),
            queryClient.prefetchQuery(queries.matchesStored(platform, name, tag)),
            queryClient.prefetchQuery(queries.analyticsStored(platform, name, tag)),
            live ? queryClient.prefetchQuery(current) : null,
          ])
          // Too slow, rate limited, or an expired key: the stored answer
          // stands, as it does in the file, and the browser asks again.
          if (queryClient.getQueryState(current.queryKey)?.status === 'error') {
            queryClient.removeQueries({ queryKey: current.queryKey, exact: true })
          }
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
            // The header art is the top pick's splash, looked up in this list.
            // Without it in the HTML the page's largest image waited for
            // hydration and a request: 1.9 s to paint against the champion
            // page's 0.8 s (2026-09-24).
            queryClient.prefetchQuery(queries.champions()),
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
        path: 'champions',
        lazy: page(() => import('./routes/Champions')),
        handle: handle(({ queryClient }) => queryClient.prefetchQuery(queries.championIndex())),
      },
      // The bare path is the champion's main role; a role's own page carries
      // the role as a path word (`/champions/pantheon/support`), so each has
      // an address to prerender and index. One module serves both.
      { path: 'champions/:championId', lazy: page(() => import('./routes/Champion')), handle: handle(prefetchChampion) },
      {
        path: 'champions/:championId/:role',
        lazy: page(() => import('./routes/Champion')),
        handle: handle(prefetchChampion),
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
