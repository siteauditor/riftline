import type { Profile } from './api'

/**
 * A profile's address, and when the page moves to another one.
 *
 * A Riot ID names one account, and the account plays on one shard: its home,
 * as Riot's active-region lookup names it (`home_platform` in the API's
 * answer). A profile opened under a shard where the account holds neither a
 * rank nor a stored game (`shard: 'absent'`) moves to the home's address. One
 * opened under an alias or another spelling of its own address (`euw` for
 * `euw1`, `th2` for `sg2`, `dekap` for `Dekap`) moves to the canonical one,
 * so a player has one page, one cache entry and one canonical link.
 */

export type ProfileTab = 'champions' | 'mastery' | 'live'

/**
 * The path of a profile. Every segment is encoded as `encodeURIComponent`
 * encodes it, which is how the API writes the sitemap (`seo.encode_path`), so
 * a link and the canonical agree to the byte. Build every summoner link with
 * this, never by hand.
 */
export function summonerPath(platform: string, name: string, tag: string, tab?: ProfileTab): string {
  const base = `/summoner/${encodeURIComponent(platform)}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`
  return tab ? `${base}/${tab}` : base
}

/** The id a game's row carries on a profile, which the form strip's bars name. */
export const gameAnchor = (matchId: string) => `game-${matchId}`

/** The shard whose page this is: the second shard shown, or the home. */
export function canonicalPlatform(profile: Pick<Profile, 'shard' | 'platform' | 'home_platform'>): string {
  return profile.shard === 'second' ? profile.platform : profile.home_platform
}

/** History state after a move to the home: the region label of the address
 *  that was opened, so the page can say why it moved. */
export interface MovedState {
  movedFrom: string
}

export function movedFrom(state: unknown): string | null {
  if (typeof state !== 'object' || state === null) return null
  const value = (state as Partial<MovedState>).movedFrom
  return typeof value === 'string' && value ? value : null
}

export interface ProfileMove {
  /** The new address, with the query string kept. */
  to: string
  /** The answer that address gets, so the page there does not ask again. */
  seed: { platform: string; name: string; tag: string; profile: Profile }
  state: MovedState | null
}

/**
 * Where a profile opened at `params` should be instead, or null to stay.
 *
 * `state` is the history state the page arrived with. After one move to the
 * home the page stays where it is whatever the answer says, with the old
 * notice: a home that answered "absent" again would otherwise move for ever.
 */
export function profileRedirect({
  params,
  search,
  profile,
  state,
}: {
  params: { platform: string; name: string; tag: string }
  search: string
  profile: Profile
  state: unknown
}): ProfileMove | null {
  const name = profile.game_name
  const tag = profile.tag_line
  if (!name || !tag) return null

  if (profile.shard === 'absent') {
    if (movedFrom(state) !== null) return null
    const home = profile.home_platform
    // What the home's own address answers: the same data, as the home.
    const atHome: Profile = {
      ...profile,
      platform: home,
      platform_label: profile.home_platform_label,
      shard: 'home',
      plays_on: null,
      plays_on_label: null,
      identity_from_plays_on: false,
    }
    return {
      to: summonerPath(home, name, tag) + search,
      seed: { platform: home, name, tag, profile: atHome },
      state: { movedFrom: profile.platform_label },
    }
  }

  const platform = profile.platform
  if (params.platform === platform && params.name === name && params.tag === tag) return null
  return {
    to: summonerPath(platform, name, tag) + search,
    seed: { platform, name, tag, profile },
    // A note from a move just made stays with the page it led to.
    state: movedFrom(state) !== null ? (state as MovedState) : null,
  }
}
