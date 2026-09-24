import { describe, expect, it } from 'vitest'

import type { Analytics, ChampionDetail, Profile } from './api'
import { fallbackLines, profileSummary } from './prose'

const solo = {
  queue: 'RANKED_SOLO_5x5',
  queue_label: 'Ranked Solo/Duo',
  tier: 'CHALLENGER',
  division: 'I',
  league_points: 2144,
  wins: 395,
  losses: 321,
  win_rate: 395 / 716,
  games: 716,
  hot_streak: false,
  inactive: false,
  numeric_rank: 9000,
}

const profile = {
  riot_id: 'Hide on bush#KR1',
  game_name: 'Hide on bush',
  tag_line: 'KR1',
  platform: 'kr',
  platform_label: 'KR',
  ranks: [solo],
} as unknown as Profile

const analytics = {
  games_analysed: 37,
  roles: [{ position: 'MIDDLE', games: 33, share: 0.89, win_rate: 0.7 }],
  totals: { win_rate: 0.68, kda: 3.37, cs_per_min: 6.6 },
  champions: [{ champion: { id: 1, name: 'Ahri' }, games: 8, win_rate: 1 }],
  score_profile: [
    { position: 'MIDDLE', scored_games: 25, enough: true, avg_score: 6.4, avg_placement: 3.8, mvp: 7 },
  ],
} as unknown as Analytics

describe('profileSummary', () => {
  it('says the rank and record first, so the sentence can stand as the description', () => {
    const [first] = profileSummary(profile)
    expect(first).toBe(
      'Hide on bush#KR1 is Challenger with 2,144 LP in ranked solo on KR, 395 wins and 321 losses this season (55%).',
    )
    expect(profileSummary(profile)).toHaveLength(1)
  })

  it('names a missing placement rather than inventing one', () => {
    const unranked = { ...profile, ranks: [] } as unknown as Profile
    expect(profileSummary(unranked)[0]).toBe(
      'Hide on bush#KR1 plays on KR and has no ranked solo placement this season.',
    )
  })

  it('reads the stored games, the score where there are enough, and the most played champion', () => {
    const out = profileSummary(profile, analytics)
    expect(out).toHaveLength(4)
    expect(out[1]).toBe(
      'Over the 37 games Riftline holds, Hide on bush plays mid in 89% of games and wins 68%, at a 3.37 KDA and 6.6 CS a minute.',
    )
    expect(out[2]).toBe(
      'As mid, their Riftline score averages 6.4 over 25 scored games, an average placement of 3.8 of 10 in the lobby, with 7 MVP games.',
    )
    expect(out[3]).toBe('Their most played champion is Ahri: 8 games at 100%.')
  })

  it('withholds the score sentence below the floor, like the panel does', () => {
    const thin = {
      ...analytics,
      score_profile: [{ ...analytics.score_profile[0], enough: false }],
      champions: [],
    } as unknown as Analytics
    const out = profileSummary(profile, thin)
    expect(out).toHaveLength(2)
    expect(out.join(' ')).not.toContain('Riftline score')
  })

  it('says nothing about games when there are none', () => {
    const empty = { ...analytics, games_analysed: 0 } as unknown as Analytics
    expect(profileSummary(profile, empty)).toHaveLength(1)
  })
})

describe('fallbackLines', () => {
  const served = {
    patch: '16.18',
    position: 'MIDDLE',
    positions: [
      { position: 'MIDDLE', games: 900, share: 0.9, win_rate: 0.5 },
      { position: 'TOP', games: 100, share: 0.1, win_rate: 0.5 },
    ],
    requested_patch: null,
    requested_position: null,
  }

  it('says which role was asked for and which is on screen, with its share', () => {
    const d = { ...served, requested_position: 'JUNGLE' } as unknown as ChampionDetail
    expect(fallbackLines(d, 'Ahri')).toEqual([
      "Ahri has no jungle games on patch 16.18. This is mid, where 90% of Ahri's games are.",
    ])
  })

  it('says a patch the site does not hold was replaced', () => {
    const d = { ...served, requested_patch: '16.9' } as unknown as ChampionDetail
    expect(fallbackLines(d, 'Ahri')).toEqual(['Riftline holds no games of Ahri on patch 16.9, so this is patch 16.18.'])
  })

  it('says nothing when the page is what the link asked for', () => {
    expect(fallbackLines(served as unknown as ChampionDetail, 'Ahri')).toEqual([])
  })
})
