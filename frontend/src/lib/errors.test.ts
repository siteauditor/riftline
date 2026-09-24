import { describe, expect, it } from 'vitest'

import { ApiError } from './api'
import { operatorHint, publicErrorText } from './errors'

// What a visitor must never be told: how to fix the server.
const OPERATOR_WORDS = ['RIOT_API_KEY', 'backend/.env', 'developer.riotgames', 'development key', '24 hours']

const failures = [
  new ApiError(404, 'No Riot account is called Nobody#0000.'),
  new ApiError(429, 'Too many lookups at once. Try again in a few seconds.', { retry_after: 7 }),
  new ApiError(429, 'Too many adds from this address in an hour. Try again later.'),
  new ApiError(503, 'Live lookups are paused right now.', { hint: 'expired_api_key' }),
  new ApiError(410, 'Riot no longer offers this lookup.'),
  new ApiError(403, 'This lookup is not available right now.', { hint: 'endpoint_unavailable' }),
  new ApiError(502, "Riot's API is not responding right now."),
  new ApiError(524, ''),
  new ApiError(500, 'Internal Server Error'),
  new Error('boom'),
  'not even an error',
]

describe('publicErrorText', () => {
  it('never tells a visitor how to fix the server', () => {
    for (const failure of failures) {
      for (const context of [undefined, 'Caps#EUW']) {
        const { title, body } = publicErrorText(failure, context)
        for (const word of OPERATOR_WORDS) {
          expect(`${title} ${body}`).not.toContain(word)
        }
      }
    }
  })

  it('says a paused key in the site words, and that stored pages still work', () => {
    const { title, body } = publicErrorText(failures[3])
    expect(title).toBe('Live data is paused')
    expect(body).toContain('Stored profiles')
  })

  it('names the Riot ID that was not found, and nothing about regions', () => {
    const { title, body } = publicErrorText(failures[0], 'Caps#EUW')
    expect(title).toBe('No player found')
    expect(body).toBe('No Riot account is called Caps#EUW. Check the spelling and the tag after the #.')
  })

  it("keeps the site's own limits in their own words", () => {
    expect(publicErrorText(failures[2]).body).toBe(
      'Too many adds from this address in an hour. Try again later.',
    )
    expect(publicErrorText(failures[1]).title).toBe('Too many lookups at once')
  })

  it('blames a gateway timeout on the wait, not on Riot', () => {
    expect(publicErrorText(failures[7]).title).toBe('That took too long')
  })
})

describe('operatorHint', () => {
  it('tells whoever runs the server what to do, in development', () => {
    expect(import.meta.env.DEV).toBe(true)
    expect(operatorHint(failures[3])).toContain('RIOT_API_KEY')
    expect(operatorHint(failures[1])).toContain('100 requests')
    expect(operatorHint(failures[2])).toBeNull()
    expect(operatorHint(failures[0])).toBeNull()
  })
})
