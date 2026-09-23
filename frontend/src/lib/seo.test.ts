import { describe, expect, it } from 'vitest'

import { ORIGIN } from './head'
import { breadcrumbs, heads } from './seo'

describe('heads.profile', () => {
  it('encodes the Riot ID the way the sitemap does and prefers the page brief', () => {
    const head = heads.profile('Hide on bush#KR1', 'kr', 'Challenger', 'Hide on bush#KR1 is Challenger.')
    expect(head.path).toBe('/summoner/kr/Hide%20on%20bush/KR1')
    expect(head.title).toBe('Hide on bush#KR1, Challenger, KR stats | Riftline')
    expect(head.description).toBe('Hide on bush#KR1 is Challenger.')
    expect(head.noindex).toBeUndefined()
  })

  it('falls back to a description that names the region', () => {
    const head = heads.profile('Caps#EUW', 'euw1')
    expect(head.title).toBe('Caps#EUW, EUW stats | Riftline')
    expect(head.description).toContain('Caps#EUW on EUW')
  })
})

describe('heads.profileTab', () => {
  it('keeps the tab under the profile path', () => {
    const head = heads.profileTab('Caps#EUW', 'euw1', 'champions')
    expect(head.path).toBe('/summoner/euw1/Caps/EUW/champions')
    expect(head.title).toContain('champions')
  })
})

describe('breadcrumbs', () => {
  it('numbers the trail and makes every item absolute', () => {
    const list = breadcrumbs([
      { name: 'Items', path: '/items' },
      { name: 'Blade of the Ruined King', path: '/items/blade-of-the-ruined-king' },
    ]) as { '@type': string; itemListElement: { position: number; item: string }[] }
    expect(list['@type']).toBe('BreadcrumbList')
    expect(list.itemListElement.map((i) => i.position)).toEqual([1, 2])
    expect(list.itemListElement[1].item).toBe(`${ORIGIN}/items/blade-of-the-ruined-king`)
  })
})

describe('heads.group', () => {
  it('is private by design', () => {
    expect(heads.group('Team', 'abc').noindex).toBe(true)
  })
})
