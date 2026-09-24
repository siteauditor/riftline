import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'

import ArtHeader from '../ArtHeader'
import Crest from '../Crest'
import Hint from '../Hint'
import ProfileTabs from '../ProfileTabs'
import AddToGroup from '../group/AddToGroup'
import { Button } from '@/components/ui/button'
import type { Profile, QueueScope } from '../../lib/api'
import { useNow } from '../../lib/clock'
import { publicErrorText } from '../../lib/errors'
import { ordinal, pct, tierColor, tierLabel, timeAgo } from '../../lib/format'

// Matches the server's refresh floor (REFRESH_FLOOR_SECONDS): an Update inside
// it would be answered from the cache, so the button waits it out instead of
// pretending to have fetched.
const UPDATE_COOLDOWN_MS = 60_000

// The leaderboard's page size, to link a ladder position to the right page.
const LADDER_PAGE = 50

/**
 * Who this is, their rank in one line, and the tabs.
 *
 * Compact on purpose. On a 412x839 phone the old header was a 64px icon on
 * its own row, the name, a rank line, an update row and the tabs, 285px under
 * the site header, and under it came one rank card per queue: the first game
 * started at 1,128px, past the first screen (2026-09-24). The icon now sits
 * beside the name, the season record joins the rank line, level and region
 * join the update line, and the full rank cards wait in the rail.
 */
export default function ProfileHeader({
  profile,
  art,
  platform,
  name,
  tag,
  scope,
  onUpdate,
}: {
  profile: Profile
  art: string | null
  /** The URL's own, which the tabs link from. */
  platform: string
  name: string
  tag: string
  scope: QueueScope
  onUpdate: () => Promise<void>
}) {
  // Solo queue first: it is the rank people mean when they say "my rank".
  const headline = profile.ranks.find((r) => r.tier) ?? null
  const accent = tierColor(headline?.tier)
  return (
    <ArtHeader art={art} compact>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 items-center gap-3 sm:gap-4">
          {profile.profile_icon_url && (
            <img
              src={profile.profile_icon_url}
              alt=""
              className="size-10 shrink-0 self-start ring-1 ring-line sm:size-16 sm:self-center"
            />
          )}
          <div className="min-w-0">
            <h1 className="display text-[clamp(1.6rem,4.5vw,3rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
              {profile.game_name}
              <span className="ml-2 text-[0.5em] font-600 text-ink-faint">#{profile.tag_line}</span>
            </h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-dim">
              {headline ? (
                <>
                  <span className="flex items-center gap-1.5">
                    <Crest tier={headline.tier} division={headline.division} size="inline" />
                    <span
                      className="display text-base font-700 uppercase tracking-wide"
                      style={{ color: accent } as CSSProperties}
                    >
                      {tierLabel(headline.tier, headline.division)}
                    </span>
                    <span className="tnum">{headline.league_points.toLocaleString('en-US')} LP</span>
                  </span>
                  <span className="tnum text-xs">
                    <span className="text-win">{headline.wins}W</span>{' '}
                    <span className="text-loss">{headline.losses}L</span>{' '}
                    <span className="text-ink-faint">this season, {pct(headline.win_rate)}</span>
                  </span>
                  {profile.ladder && <LadderChip ladder={profile.ladder} />}
                </>
              ) : (
                <span className="text-ink-faint">Unranked this season</span>
              )}
            </p>
          </div>
        </div>

        {/* Last on a phone, from the left, under the line they belong with;
            beside the name from lg. */}
        <ProfileTabs
          platform={platform}
          name={name}
          tag={tag}
          scope={scope}
          className="max-lg:order-last lg:ml-auto"
        />

        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-faint">
          <span>Level {profile.summoner_level ?? 'unknown'}</span>
          <span>{profile.platform_label}</span>
          <UpdateControl updatedAt={profile.updated_at} onUpdate={onUpdate} />
          <AddToGroup platform={platform} riotId={profile.riot_id} />
        </div>
      </div>
    </ArtHeader>
  )
}

/** "#257 EUW": where they stand on the stored solo ladder of their shard. */
function LadderChip({ ladder }: { ladder: NonNullable<Profile['ladder']> }) {
  const now = useNow()
  const params = new URLSearchParams({
    platform: ladder.platform,
    tier: ladder.tier,
    page: String(Math.ceil(ladder.tier_position / LADDER_PAGE)),
    // The ladder marks and scrolls to the row, so the player is not one of 50.
    rank: String(ladder.tier_position),
  })
  const tier = tierLabel(ladder.tier)
  const label =
    ladder.position !== null
      ? `#${ladder.position.toLocaleString('en-US')} ${ladder.platform_label}`
      : `#${ladder.tier_position.toLocaleString('en-US')} in ${tier}`
  const title =
    (ladder.position !== null
      ? `${ordinal(ladder.position)} on the ${ladder.platform_label} solo ladder, ` +
        `${ordinal(ladder.tier_position)} in ${tier}. `
      : `${ordinal(ladder.tier_position)} in ${tier} on ${ladder.platform_label}. `) +
    `From the ladder as it stood ${timeAgo(ladder.as_of, now)}.`
  return (
    <Hint text={title}>
      <Link
        to={`/leaderboards?${params.toString()}`}
        className="tnum rounded-sm bg-raised px-1.5 py-0.5 text-xs font-600 text-ink transition-colors hover:text-gold-bright"
      >
        {label}
      </Link>
    </Hint>
  )
}

/**
 * How old the rank shown is, and a way to ask Riot again.
 *
 * Waits out the server's refresh floor after each update, because an Update
 * inside it would come back from the cache and only look like it worked.
 */
function UpdateControl({
  updatedAt,
  onUpdate,
}: {
  updatedAt: number | null
  onUpdate: () => Promise<void>
}) {
  const now = useNow()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const cooling = updatedAt !== null && now - updatedAt < UPDATE_COOLDOWN_MS

  async function run() {
    setBusy(true)
    setFailed(null)
    try {
      await onUpdate()
    } catch (error) {
      setFailed(publicErrorText(error).title)
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
      {updatedAt !== null && (
        <span>Updated {now - updatedAt < 60_000 ? 'just now' : timeAgo(updatedAt, now)}</span>
      )}
      <Hint text={cooling ? 'Riot was asked less than a minute ago.' : 'Ask Riot for the latest rank and games.'}>
        {/* A disabled button takes no pointer events, so the hint sits on a
            span around it. */}
        <span tabIndex={cooling ? 0 : -1} className="inline-flex rounded-md outline-none">
          <Button variant="outline" size="xs" onClick={run} disabled={busy || cooling} className="font-600">
            {busy ? 'Updating…' : 'Update'}
          </Button>
        </span>
      </Hint>
      {failed && (
        <span role="alert" className="text-loss">
          {failed}
        </span>
      )}
    </span>
  )
}
