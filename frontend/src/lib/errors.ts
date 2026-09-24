import { ApiError } from './api'

/**
 * What a failed request tells a visitor, in the site's words.
 *
 * Never how to fix the server: until 2026-09-24 every visitor who met an
 * expired key was told to generate one at developer.riotgames.com and put it
 * in backend/.env. What the operator needs is `operatorHint`, shown only in
 * development, and the API's log, which names the fix
 * (docs/deploy.md, "Rotating the Riot key").
 */
export function publicErrorText(error: unknown, context?: string): { title: string; body: string } {
  const api = error instanceof ApiError ? error : null
  switch (api?.kind) {
    case 'not_found':
      // Not every 404 is a missing player: the meta and draft endpoints
      // answer 404 for "not enough data yet", and say what that means.
      return context
        ? {
            title: 'No player found',
            body: `No Riot account is called ${context}. Check the spelling and the tag after the #.`,
          }
        : { title: 'Nothing to show yet', body: api.message }
    case 'rate_limited':
      // Riot's limit carries a retry time; the site's own limits on groups
      // do not, and their message says which limit it was.
      return api.retryAfter === undefined
        ? { title: 'Too many requests', body: api.message }
        : {
            title: 'Too many lookups at once',
            body: 'Riftline asks Riot for a limited number of lookups every two minutes. This clears on its own.',
          }
    case 'expired_key':
      return {
        title: 'Live data is paused',
        body: 'Riftline cannot ask Riot for live data right now. Stored profiles, the tier list and the champion pages still work.',
      }
    case 'gone':
      return { title: 'Riot removed this lookup', body: api.message }
    case 'unavailable':
      // The key is fine, so nothing here says it is not.
      return { title: 'Not available', body: api.message }
    case 'upstream':
      // A gateway that gave up waiting for us is not Riot's fault.
      return api.status === 504 || api.status === 524
        ? { title: 'That took too long', body: 'The server did not answer in time. Try again in a moment.' }
        : { title: "Riot's API isn't responding", body: "This is on Riot's side. It usually clears within a few minutes." }
    default:
      return { title: 'Something went wrong', body: api?.message ?? 'An unexpected error occurred.' }
  }
}

/** What whoever runs the server should do, in development only. */
export function operatorHint(error: unknown): string | null {
  if (!import.meta.env.DEV || !(error instanceof ApiError)) return null
  if (error.kind === 'expired_key') {
    return 'Development keys expire 24 hours after they are issued. Put a new one in backend/.env as RIOT_API_KEY and restart the API.'
  }
  if (error.kind === 'rate_limited' && error.retryAfter !== undefined) {
    return 'A development key allows 100 requests every two minutes.'
  }
  return null
}
