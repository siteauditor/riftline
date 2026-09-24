import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import FormStrip from '../FormStrip'
import MatchRow from '../MatchRow'
import RankCard from '../RankCard'
import RecentChampions from './RecentChampions'
import StatusBand from './StatusBand'
import { SectionTitle } from '../Stat'
import { EmptyState, MatchListSkeleton } from '../StateViews'
import type { IdleSummary, MatchSummary, Profile } from '../../lib/api'
import { tierColor, timeAgo } from '../../lib/format'
import { summonerPath } from '../../lib/profileAddress'

/**
 * The live page when nobody is in a game, which is almost always.
 *
 * Measured on 2026-09-21: 31 lookups against production, covering the active
 * EUW and NA challengers and everyone in that week's best games, found nobody
 * playing. This is the page, and it used to be a dashed box with two sentences
 * in it.
 *
 * Everything here is composed from parts the profile already uses, so the idle
 * page costs one history read and no new UI: the match row expands into the
 * full scoreboard, the form strip is the same twenty games, and the rank cards
 * are the one line variant the profile shows on a phone.
 */
export default function IdleView({
  idle,
  profile,
  matches,
  loading,
  platform,
  name,
  tag,
  poll,
}: {
  idle: IdleSummary
  profile: Profile | undefined
  matches: MatchSummary[]
  loading: boolean
  platform: string
  name: string
  tag: string
  /** The countdown and the check button, owned by the page. */
  poll: ReactNode
}) {
  const overview = summonerPath(platform, name, tag)
  const ranked = profile?.ranks.find((r) => r.tier) ?? profile?.ranks[0]
  const accent = tierColor(ranked?.tier)
  // The newest game Riot knows about when the history has loaded, and the
  // newest one we hold otherwise. They are usually the same game.
  const last = matches.find((m) => !m.is_remake)
  const lastPlayedAt = last?.game_creation ?? idle.last_game?.game_creation ?? null

  return (
    <div className="space-y-5">
      <StatusBand
        accent={accent}
        iconUrl={profile?.profile_icon_url}
        title="Not in a game right now"
        detail={
          lastPlayedAt
            ? `Last played ${timeAgo(lastPlayedAt)}. This page checks Riot every minute while it is open.`
            : 'This page checks Riot every minute while it is open.'
        }
        aside={poll}
      />

      {idle.stored_games === 0 && !loading && matches.length === 0 ? (
        <EmptyState
          title="No games stored yet"
          body="We hold no games for this player. Open their overview and the last twenty load from Riot, then this page can show them."
        />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
          <div className="min-w-0 space-y-5">
            <section>
              <SectionTitle
                eyebrow="From storage"
                title="Last game"
                aside={
                  <Link
                    to={overview}
                    className="text-ink-dim underline decoration-line underline-offset-2 hover:text-gold-bright"
                  >
                    All {idle.stored_games} stored games
                  </Link>
                }
              />
              <div className="mt-1 border-t border-line-soft">
                {last ? (
                  <MatchRow match={last} platform={platform} puuid={profile?.puuid ?? ''} />
                ) : loading ? (
                  <MatchListSkeleton rows={1} />
                ) : (
                  <p className="px-1 py-4 text-sm text-ink-faint">
                    The most recent game we hold is{' '}
                    {idle.last_game
                      ? `${idle.last_game.champion.name}, ${timeAgo(idle.last_game.game_creation)}`
                      : 'not loaded yet'}
                    . Open the overview to load their history from Riot.
                  </p>
                )}
              </div>
            </section>

            {matches.length > 0 && <FormStrip matches={matches} />}
          </div>

          <div className="space-y-5">
            {profile?.ranks.map((rank) => (
              <RankCard key={rank.queue} rank={rank} compact />
            ))}
            <RecentChampions matches={matches} />
            <p className="text-[11px] leading-relaxed text-ink-faint">
              These are the games Riftline has stored, which is not the same as
              everything they have played. Riot publishes a live game only while
              it is running, so this page watches for one.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
