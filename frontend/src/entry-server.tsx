import { StrictMode } from 'react'
import { renderToString } from 'react-dom/server'
import { dehydrate, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createStaticHandler, createStaticRouter, StaticRouterProvider } from 'react-router-dom'

import { setServerNow } from './lib/clock'
import { HeadContext, jsonForHtml, renderHeadHtml, type PageHead } from './lib/head'
import { routes, type RouteHandle } from './routes'

export { jsonForHtml, renderHeadHtml }

/**
 * Render one page to HTML, the way the prerenderer needs it (and, with
 * `live`, the way prerender/live.mjs does, on request).
 *
 * The same route table and the same components as the browser. The matched
 * routes' `prefetch` handles fill a QueryClient first, so the components find
 * their data in the cache and render it; the cache is then dehydrated into the
 * page for the browser to pick up. Whatever the page declared for its head is
 * collected rather than written to a document, since there is none.
 */

export interface Rendered {
  status: number
  /** Epoch ms of this render, for the page to hydrate its relative times from. */
  renderedAt: number
  html: string
  head: PageHead | null
  state: unknown
  /** Queries that failed during prefetch: the page rendered its error state. */
  errors: string[]
}

export async function render(
  url: string,
  { noindex = false, live = false } = {},
): Promise<Rendered> {
  const handler = createStaticHandler(routes)
  const request = new Request(new URL(url, 'http://prerender.local'))
  const context = await handler.query(request)
  if (context instanceof Response) {
    return {
      status: context.status,
      renderedAt: Date.now(),
      html: '',
      head: null,
      state: null,
      errors: [`router answered ${context.status}`],
    }
  }

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  const search = new URL(request.url).searchParams
  const errors: string[] = []
  for (const match of context.matches) {
    const prefetch = (match.route.handle as RouteHandle | undefined)?.prefetch
    if (!prefetch) continue
    try {
      await prefetch({ params: match.params, search, queryClient, live })
    } catch (error) {
      errors.push(String(error))
    }
  }
  // prefetchQuery never throws; a failed query sits in the cache as an error.
  for (const query of queryClient.getQueryCache().getAll()) {
    if (query.state.status === 'error') {
      errors.push(`${JSON.stringify(query.queryKey)}: ${String(query.state.error)}`)
    }
  }

  const collector = {
    head: null as PageHead | null,
    set(head: PageHead) {
      this.head = head
    },
  }
  const router = createStaticRouter(handler.dataRoutes, context)
  const renderedAt = Date.now()
  setServerNow(renderedAt)
  const html = renderToString(
    <StrictMode>
      <HeadContext.Provider value={collector}>
        <QueryClientProvider client={queryClient}>
          <StaticRouterProvider router={router} context={context} />
        </QueryClientProvider>
      </HeadContext.Provider>
    </StrictMode>,
  )
  // A page the manifest marks as not indexable keeps `follow`: it is thin,
  // not private, and its links to fuller pages still count.
  const head = collector.head
    ? noindex && !collector.head.noindex
      ? { ...collector.head, noindex: true, robots: 'noindex, follow' as const }
      : collector.head
    : null
  setServerNow(null)
  // Errors travel with the successes. Left out, a query that failed on the
  // server would be pending in the browser, which renders a skeleton where
  // the server rendered nothing, and React would throw the page away over
  // it. Hydrated as an error it renders the same, and refetches on mount.
  const state = dehydrate(queryClient, {
    shouldDehydrateQuery: (query) => query.state.status === 'success' || query.state.status === 'error',
  })
  return { status: context.statusCode, renderedAt, html, head, state, errors }
}
