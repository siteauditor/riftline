import { describe, expect, it } from 'vitest'

import { DEFAULT_LADDER, queries } from './queries'

describe('queries', () => {
  it('gives the stored profile answers keys of their own, apart from the live ones', () => {
    const args = ['euw1', 'Annie IRL', 'Annie'] as const
    const stored = [
      queries.profileStored(...args).queryKey,
      queries.matchesStored(...args).queryKey,
      queries.analyticsStored(...args).queryKey,
    ]
    const prefixes = stored.map((k) => k[0])
    expect(new Set(prefixes).size).toBe(3)
    // The live page keys these by 'profile', 'matches' and 'analytics'; a
    // stored key that started the same way would be found by the live
    // page's invalidations and refetched from Riot.
    expect(prefixes).not.toContain('profile')
    expect(prefixes).not.toContain('matches')
    expect(prefixes).not.toContain('analytics')
  })

  it('builds the same key for the same inputs, whoever asks', () => {
    const slice = { patch: '16.18', queueId: 420, bracket: null, position: 'TOP', minGames: 5 }
    expect(queries.champion('aatrox', slice).queryKey).toEqual(queries.champion('aatrox', { ...slice }).queryKey)
    expect(queries.leaderboard(DEFAULT_LADDER.platform, DEFAULT_LADDER).queryKey).toEqual([
      'leaderboard', 'euw1', 420, 'CHALLENGER', 'I', 1,
    ])
  })
})
