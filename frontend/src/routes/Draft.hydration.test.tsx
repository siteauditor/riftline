import { act } from 'react'
import { hydrateRoot } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import Draft from './Draft'

/**
 * The draft page hydrated against HTML prerendered for a different URL.
 *
 * nginx serves the `/draft` file for every `/draft?...` link, and a returning
 * visitor's browser remembers a region and a Riot ID the server never saw. Both
 * made the first client render differ from the HTML, and React threw the page
 * away with error #418 (measured on production 2026-09-24). The browser smoke
 * test cannot see this in CI, where the corpus is empty and the board is not
 * drawn, so it is checked here.
 */

const CHAMPIONS = {
  version: 'test',
  champions: [
    { id: 238, name: 'Zed', slug: 'zed', key: 'Zed', icon_url: null, title: null, tags: [], splash_url: null, art_url: null, tile_url: null },
    { id: 103, name: 'Ahri', slug: 'ahri', key: 'Ahri', icon_url: null, title: null, tags: [], splash_url: null, art_url: null, tile_url: null },
  ],
}
const CORPUS = { slices: [], brackets: ['ALL'], total_matches: 1_446, latest_game_at: null, latest_ingest_at: null }

function seededClient(): QueryClient {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData(['champions'], CHAMPIONS)
  client.setQueryData(['corpus'], CORPUS)
  return client
}

function page(url: string, client: QueryClient) {
  const router = createMemoryRouter([{ path: '/draft', element: <Draft /> }], { initialEntries: [url] })
  return (
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}

describe('the draft page hydrating a link', () => {
  beforeEach(() => {
    // The draft request after hydration: answered never, so the page stays on
    // its skeleton and the test sees only what hydration did.
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    localStorage.setItem('riftline.region', 'kr')
    localStorage.setItem('riftline.riotId', 'Faker#KR1')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('matches the HTML for the bare path, then shows the board the link asked for', async () => {
    const html = renderToString(page('/draft', seededClient()))
    const container = document.createElement('div')
    container.innerHTML = html
    document.body.appendChild(container)

    const recoverable: unknown[] = []
    await act(async () => {
      hydrateRoot(container, page('/draft?role=TOP&enemies=238&lane=238', seededClient()), {
        onRecoverableError: (error) => recoverable.push(error),
      })
    })

    expect(recoverable).toEqual([])
    const top = [...container.querySelectorAll('button[aria-pressed]')].find((b) => b.textContent?.includes('Top'))
    expect(top?.getAttribute('aria-pressed')).toBe('true')
    // The remembered region and Riot ID arrive after hydration, not during it.
    expect(container.querySelector('input[placeholder="Caps#EUW"]')?.getAttribute('value') ?? '').toBe('Faker#KR1')
    expect(container.textContent).toContain('KR')
  })
})
