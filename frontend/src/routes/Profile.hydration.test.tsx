import { act } from 'react'
import { hydrateRoot } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { ApiError } from '@/lib/api'
import { queries } from '@/lib/queries'
import { emptyAnalytics, emptyHistory, PLAYER, profile, storedHistory, storedProfile } from '@/test/fixtures/profile'

import Profile from './Profile'

/**
 * A prerendered profile hydrating a link with filters in it.
 *
 * nginx serves the bare path's file for `?queue=420&champion=412`, and the
 * URL's filters read as empty until hydration has finished. The history used
 * to be asked for at once, so the unfiltered page was fetched and then the
 * filtered one. It is asked now only after hydration and after Riot has
 * answered for the profile, once, with the filters the link carries: an older
 * link's queue id as the scope word it now means (420 is solo).
 */

const { platform, name, tag } = PLAYER
const BARE = `/summoner/${platform}/${name}/${tag}`

function prerendered(): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['champions'], { version: 'test', champions: [] })
  client.setQueryData(queries.profileStored(platform, name, tag).queryKey, storedProfile)
  client.setQueryData(queries.matchesStored(platform, name, tag).queryKey, storedHistory)
  client.setQueryData(queries.analyticsStored(platform, name, tag).queryKey, emptyAnalytics)
  return client
}

function page(url: string, client: QueryClient) {
  const router = createMemoryRouter([{ path: '/summoner/:platform/:name/:tag', element: <Profile /> }], {
    initialEntries: [url],
  })
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>
  )
}

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

async function hydrate(url: string, answers: (path: string) => Promise<Response>) {
  const requests: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string) => {
      requests.push(input)
      return answers(input)
    }),
  )
  const container = document.createElement('div')
  container.innerHTML = renderToString(page(BARE, prerendered()))
  document.body.appendChild(container)
  const recoverable: unknown[] = []
  await act(async () => {
    hydrateRoot(container, page(url, prerendered()), { onRecoverableError: (error) => recoverable.push(error) })
  })
  // Let the answers land and the queries they enable run.
  for (let i = 0; i < 5; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
  return { container, requests, recoverable }
}

describe('a prerendered profile hydrating a filtered link', () => {
  beforeEach(() => {
    localStorage.clear()
    // jsdom has none; the tabs' sliding bar measures itself with one.
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    )
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  it('matches the HTML, then asks for the filtered history once', async () => {
    const { requests, recoverable } = await hydrate(`${BARE}?queue=420&champion=412`, (path) => {
      if (path.includes('/matches')) return json(emptyHistory)
      if (path.includes('/analytics')) return json(emptyAnalytics)
      if (path.includes('/rank-history')) return new Promise(() => {})
      return json(profile)
    })

    expect(recoverable).toEqual([])
    const histories = requests.filter((r) => r.includes('/matches'))
    expect(histories).toHaveLength(1)
    expect(histories[0]).toContain('scope=solo')
    expect(histories[0]).toContain('champion=412')
  })

  it('asks nothing of the history before Riot has answered for the profile', async () => {
    const { requests } = await hydrate(`${BARE}?queue=420`, (path) =>
      path.includes('/matches') || path.includes('/analytics') ? json(emptyHistory) : new Promise(() => {}),
    )
    expect(requests.filter((r) => r.includes('/matches'))).toEqual([])
  })

  it('reads storage, and says so, when live lookups are paused', async () => {
    const paused = { detail: 'Live lookups are paused right now.', hint: 'expired_api_key' }
    const { container, requests } = await hydrate(BARE, (path) => {
      if (path.includes('source=stored')) {
        return path.includes('/matches') ? json(storedHistory) : json(emptyAnalytics)
      }
      return json(paused, 503)
    })
    expect(container.textContent).toContain('Live data is unavailable right now.')
    // The history comes from storage, not from Riot, and nothing tells the
    // visitor how to fix the server.
    expect(requests.filter((r) => r.includes('/matches') && !r.includes('source=stored'))).toEqual([])
    expect(container.textContent).not.toContain('RIOT_API_KEY')
    expect(new ApiError(503, paused.detail, paused).kind).toBe('expired_key')
  })
})
