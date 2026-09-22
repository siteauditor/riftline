import type { QueryClient } from '@tanstack/react-query'
import type { RouteObject } from 'react-router-dom'

import App from './App'
import { sliceFromParams } from './lib/searchParams'
import { DEFAULT_LADDER, queries } from './lib/queries'
import Home from './routes/Home'
import Profile from './routes/Profile'
import Mastery from './routes/Mastery'
import PlayerChampions from './routes/PlayerChampions'
import Tierlist, { MIN_GAMES as TIERLIST_MIN_GAMES } from './routes/Tierlist'
import Draft from './routes/Draft'
import Champion, { MIN_GAMES as CHAMPION_MIN_GAMES } from './routes/Champion'
import LiveGame from './routes/LiveGame'
import Item from './routes/Item'
import Items from './routes/Items'
import Leaderboard from './routes/Leaderboard'
import Match from './routes/Match'
import Method from './routes/Method'
import Score from './routes/method/Score'
import WinChance from './routes/method/WinChance'
import DeathReview from './routes/method/DeathReview'
import LaneLabels from './routes/method/LaneLabels'
import Groups from './routes/Groups'
import Group from './routes/Group'
import NotFound, { RouteError } from './routes/NotFound'

/**
 * The route table, shared by the browser and the prerenderer.
 *
 * Each route that is prerendered carries a `prefetch` in its handle: the
 * queries the page reads, fetched into a QueryClient before the page renders
 * on the server, so the HTML has its numbers and the browser hydrates from
 * the same cache instead of fetching again. The keys come from `queries`, the
 * same definitions the components use, so the two cannot drift.
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
        element: <Home />,
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
        element: <Profile />,
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
      { path: 'summoner/:platform/:name/:tag/champions', element: <PlayerChampions /> },
      { path: 'summoner/:platform/:name/:tag/mastery', element: <Mastery /> },
      { path: 'summoner/:platform/:name/:tag/live', element: <LiveGame /> },
      {
        path: 'leaderboards',
        element: <Leaderboard />,
        handle: handle(({ queryClient }) =>
          Promise.all([
            queryClient.prefetchQuery(queries.leaderboardSlices()),
            queryClient.prefetchQuery(queries.leaderboard(DEFAULT_LADDER.platform, DEFAULT_LADDER)),
          ]),
        ),
      },
      {
        path: 'tierlist',
        element: <Tierlist />,
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
        element: <Draft />,
        handle: handle(({ queryClient }) =>
          Promise.all([
            queryClient.prefetchQuery(queries.champions()),
            queryClient.prefetchQuery(queries.corpus()),
          ]),
        ),
      },
      {
        path: 'champions/:championId',
        element: <Champion />,
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
        element: <Items />,
        handle: handle(({ queryClient }) => queryClient.prefetchQuery(queries.items())),
      },
      {
        path: 'items/:itemId',
        element: <Item />,
        handle: handle(({ params, search, queryClient }) => {
          const { patch, queueId, bracket } = sliceFromParams(search, 1)
          return queryClient.prefetchQuery(queries.item(params.itemId ?? '', { patch, queueId, bracket }))
        }),
      },
      { path: 'match/:matchId', element: <Match /> },
      { path: 'method', element: <Method />, handle: handle(prefetchMethod) },
      { path: 'method/score', element: <Score />, handle: handle(prefetchMethod) },
      { path: 'method/win-chance', element: <WinChance />, handle: handle(prefetchMethod) },
      { path: 'method/death-review', element: <DeathReview />, handle: handle(prefetchMethod) },
      { path: 'method/lane-labels', element: <LaneLabels />, handle: handle(prefetchMethod) },
      { path: 'groups', element: <Groups /> },
      { path: 'g/:slug', element: <Group /> },
      // nginx serves the shell for every path it does not recognise, so the
      // router is what decides an address is not a page. Keep this last.
      { path: '*', element: <NotFound /> },
    ],
  },
]
