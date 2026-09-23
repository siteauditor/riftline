import { render } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { HeadContext, ORIGIN, type PageHead } from '../lib/head'
import Head from './Head'

const head: PageHead = { title: 'Tier list | Riftline', description: 'Every champion.', path: '/tierlist' }

describe('Head', () => {
  beforeEach(() => {
    document.head.innerHTML = '<title>Riftline</title>'
  })

  it('hands its head to the collector under the prerenderer', () => {
    const collector = {
      head: null as PageHead | null,
      set(next: PageHead) {
        this.head = next
      },
    }
    render(
      <HeadContext.Provider value={collector}>
        <Head {...head} />
      </HeadContext.Provider>,
    )
    expect(collector.head?.title).toBe('Tier list | Riftline')
    // Nothing is written to a document the prerenderer does not have.
    expect(document.title).toBe('Riftline')
  })

  it('writes the document head in the browser', () => {
    render(<Head {...head} />)
    expect(document.title).toBe('Tier list | Riftline')
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(`${ORIGIN}/tierlist`)
    expect(document.querySelectorAll('title').length).toBe(1)
  })
})
