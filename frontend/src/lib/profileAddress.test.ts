import { describe, expect, it } from 'vitest'

import type { Profile } from './api'
import { canonicalPlatform, movedFrom, profileRedirect, summonerPath } from './profileAddress'

const answer = (over: Partial<Profile> = {}): Profile => ({
  puuid: 'p',
  game_name: 'Dekap',
  tag_line: 'EUW',
  riot_id: 'Dekap#EUW',
  platform: 'euw1',
  platform_label: 'EUW',
  shard: 'home',
  home_platform: 'euw1',
  home_platform_label: 'EUW',
  summoner_level: 612,
  profile_icon_url: null,
  ranks: [],
  plays_on: null,
  plays_on_label: null,
  identity_from_plays_on: false,
  updated_at: null,
  ladder: null,
  source: 'live',
  ...over,
})

const absent = answer({
  platform: 'na1',
  platform_label: 'NA',
  shard: 'absent',
  plays_on: 'euw1',
  plays_on_label: 'EUW',
  identity_from_plays_on: true,
})

describe('summonerPath', () => {
  it('encodes each segment as encodeURIComponent does, the way the sitemap writes it', () => {
    expect(summonerPath('kr', 'Hide on bush', 'KR1')).toBe('/summoner/kr/Hide%20on%20bush/KR1')
    expect(summonerPath('euw1', 'a/b?c#d', 'E W')).toBe('/summoner/euw1/a%2Fb%3Fc%23d/E%20W')
    expect(summonerPath('kr', '페이커', 'KR1', 'mastery')).toBe(
      '/summoner/kr/%ED%8E%98%EC%9D%B4%EC%BB%A4/KR1/mastery',
    )
  })
})

describe('canonicalPlatform', () => {
  it('is the home, unless the page is a second shard of its own', () => {
    expect(canonicalPlatform(answer())).toBe('euw1')
    expect(canonicalPlatform(absent)).toBe('euw1')
    expect(canonicalPlatform(answer({ shard: 'second', platform: 'kr' }))).toBe('kr')
  })
})

describe('profileRedirect', () => {
  const at = (platform: string, name = 'Dekap', tag = 'EUW') => ({ platform, name, tag })

  it('stays on the canonical address', () => {
    expect(profileRedirect({ params: at('euw1'), search: '', profile: answer(), state: null })).toBeNull()
  })

  it('moves a shard the account holds nothing on to the home, keeping the query', () => {
    const move = profileRedirect({ params: at('na1'), search: '?queue=420', profile: absent, state: null })
    expect(move?.to).toBe('/summoner/euw1/Dekap/EUW?queue=420')
    expect(move?.state).toEqual({ movedFrom: 'NA' })
    // What the home answers for itself, so the page there does not ask again.
    expect(move?.seed.platform).toBe('euw1')
    expect(move?.seed.profile).toMatchObject({
      platform: 'euw1',
      platform_label: 'EUW',
      shard: 'home',
      plays_on: null,
      identity_from_plays_on: false,
      summoner_level: 612,
    })
  })

  it('moves only once, however the home answers', () => {
    const state = { movedFrom: 'NA' }
    expect(profileRedirect({ params: at('euw1'), search: '', profile: absent, state })).toBeNull()
  })

  it('moves an alias or another spelling to the canonical address', () => {
    const alias = profileRedirect({ params: at('euw'), search: '', profile: answer(), state: null })
    expect(alias?.to).toBe('/summoner/euw1/Dekap/EUW')
    const spelling = profileRedirect({ params: at('euw1', 'dekap', 'euw'), search: '?champion=412', profile: answer(), state: null })
    expect(spelling?.to).toBe('/summoner/euw1/Dekap/EUW?champion=412')
    expect(spelling?.seed).toMatchObject({ platform: 'euw1', name: 'Dekap', tag: 'EUW' })
    // The merged shard's old id, for an account whose home is SG2.
    const merged = answer({ platform: 'sg2', platform_label: 'SG', home_platform: 'sg2', home_platform_label: 'SG' })
    expect(profileRedirect({ params: at('th2'), search: '', profile: merged, state: null })?.to).toBe(
      '/summoner/sg2/Dekap/EUW',
    )
  })

  it('keeps the note of a move just made when the spelling is fixed after it', () => {
    const state = { movedFrom: 'NA' }
    const move = profileRedirect({ params: at('euw1', 'dekap'), search: '', profile: answer(), state })
    expect(move?.state).toEqual(state)
  })

  it('stays on a second shard of its own, spelled as Riot spells it', () => {
    const second = answer({ platform: 'kr', platform_label: 'KR', shard: 'second' })
    expect(profileRedirect({ params: at('kr'), search: '', profile: second, state: null })).toBeNull()
  })

  it('leaves an account with no Riot ID where it is', () => {
    const nameless = answer({ game_name: null, tag_line: null })
    expect(profileRedirect({ params: at('euw'), search: '', profile: nameless, state: null })).toBeNull()
  })

  it('handles names outside ASCII', () => {
    const faker = answer({ game_name: '페이커', tag_line: 'KR1', platform: 'kr', home_platform: 'kr' })
    expect(profileRedirect({ params: at('kr', '페이커', 'KR1'), search: '', profile: faker, state: null })).toBeNull()
    expect(profileRedirect({ params: at('kr', '페이커', 'kr1'), search: '', profile: faker, state: null })?.to).toBe(
      '/summoner/kr/%ED%8E%98%EC%9D%B4%EC%BB%A4/KR1',
    )
  })
})

describe('movedFrom', () => {
  it('reads only a state this page wrote', () => {
    expect(movedFrom({ movedFrom: 'NA' })).toBe('NA')
    expect(movedFrom(null)).toBeNull()
    expect(movedFrom('NA')).toBeNull()
    expect(movedFrom({ movedFrom: '' })).toBeNull()
    expect(movedFrom({ idx: 3 })).toBeNull()
  })
})
