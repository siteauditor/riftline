import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'

import AnalyticsPanel from '../components/AnalyticsPanel'
import FormStrip from '../components/FormStrip'
import MatchRow from '../components/MatchRow'
import ProfileTabs from '../components/ProfileTabs'
import RankCard from '../components/RankCard'
import { EmptyState, ErrorView, MatchListSkeleton, Spinner } from '../components/StateViews'
import { api, type MatchSummary } from '../lib/api'
import { compact, pct, tierColor, tierLabel, winRateColor } from '../lib/format'

const PAGE = 20

const QUEUE_FILTERS = [
  { id: null, label: 'All' },
  { id: 420, label: 'Solo/Duo' },
  { id: 440, label: 'Flex' },
  { id: 450, label: 'ARAM' },
]

export default function Profile() {
  const { platform = '', name = '', tag = '' } = useParams()
  const [queue, setQueue] = useState<number | null>(null)

  const profileQuery = useQuery({
    queryKey: ['profile', platform, name, tag],
    queryFn: () => api.profile(platform, name, tag),
  })

  const matchesQuery = useInfiniteQuery({
    queryKey: ['matches', platform, name, tag, queue],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      api.matches(platform, name, tag, { start: pageParam, count: PAGE, queue }),
    getNextPageParam: (last, pages) =>
      last.has_more ? pages.length * PAGE : undefined,
    enabled: profileQuery.isSuccess,
  })

  const matches: MatchSummary[] = useMemo(
    () => matchesQuery.data?.pages.flatMap((p) => p.matches) ?? [],
    [matchesQuery.data],
  )

  // Champion pool, derived from the history already on screen. No extra
  // requests, which matters when every request is rationed.
  const pool = useMemo(() => {
    const byChampion = new Map<
      number,
      { name: string; icon: string | null; games: number; wins: number; kda: number[] }
    >()
    for (const m of matches) {
      if (m.is_remake) continue
      const entry = byChampion.get(m.champion.id) ?? {
        name: m.champion.name,
        icon: m.champion.icon_url,
        games: 0,
        wins: 0,
        kda: [],
      }
      entry.games += 1
      if (m.win) entry.wins += 1
      entry.kda.push(m.kda)
      byChampion.set(m.champion.id, entry)
    }
    return [...byChampion.entries()]
      .map(([id, v]) => ({
        id,
        ...v,
        winRate: v.wins / v.games,
        avgKda: v.kda.reduce((a, b) => a + b, 0) / v.kda.length,
      }))
      .sort((a, b) => b.games - a.games)
      .slice(0, 5)
  }, [matches])

  if (profileQuery.isLoading) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <Spinner label={`Looking up ${name}#${tag}…`} />
      </div>
    )
  }

  if (profileQuery.isError) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <ErrorView
          error={profileQuery.error}
          context={`${name}#${tag}`}
          onRetry={() => profileQuery.refetch()}
        />
      </div>
    )
  }

  const profile = profileQuery.data!

  // The page takes its colour from this player's rank. Solo queue first,
  // because that is the rank people mean when they say "my rank".
  const headline = profile.ranks.find((r) => r.tier) ?? null
  const accent = tierColor(headline?.tier)

  return (
    <div style={{ '--accent': accent } as CSSProperties}>
      {/*
        A band, not a card. The rule on the left is the subject's own rank
        colour, which is the redesign's one repeated motif: a Challenger reads
        cyan here and an Iron player grey, so the colour is telling you
        something before you have read a word.
      */}
      <header className="border-b border-line-soft bg-panel/40">
        <div className="accent-edge mx-auto flex max-w-[1280px] flex-wrap items-center gap-4 py-5 pl-4 pr-4">
          {profile.profile_icon_url && (
            <img
              src={profile.profile_icon_url}
              alt=""
              className="size-14 rounded-sm ring-1 ring-line"
            />
          )}
          <div className="min-w-0">
            <h1 className="display text-[clamp(1.8rem,4vw,2.6rem)] font-700 text-ink">
              {profile.game_name}
              <span className="ml-1 text-ink-faint">#{profile.tag_line}</span>
            </h1>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-sm text-ink-dim">
              {headline && (
                <span className="display text-base font-600" style={{ color: accent }}>
                  {tierLabel(headline.tier, headline.division)}
                  <span className="tnum ml-1.5 text-ink-dim">
                    {headline.league_points.toLocaleString()} LP
                  </span>
                </span>
              )}
              <span className="text-ink-faint">Level {profile.summoner_level ?? '–'}</span>
              <span className="text-ink-faint">{profile.platform_label}</span>
            </p>
          </div>

          <ProfileTabs platform={platform} name={name} tag={tag} />
        </div>
      </header>

      <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-6">
        {/*
          A Riot ID resolves across a whole region, but a summoner record lives
          on one shard. Searching the wrong region got this far and then showed
          no avatar, "Level -" and "Unranked this season": three blanks that
          looked like facts about the player rather than about the search.
        */}
        {profile.plays_on && (
          <p className="accent-edge mb-5 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
            <span className="text-ink">
              {profile.riot_id} has no games on {profile.platform_label}.
            </span>{' '}
            This account plays on {profile.plays_on_label}
            {profile.identity_from_plays_on
              ? ', so the level and icon here are theirs and the rank is blank.'
              : ', so the level, icon and rank are blank here.'}{' '}
            <Link
              to={`/summoner/${profile.plays_on}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
              className="border-b border-gold/60 text-gold-bright transition-colors hover:border-gold-bright"
            >
              Open their {profile.plays_on_label} profile
            </Link>
          </p>
        )}

        <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
        {/* Left rail */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          {profile.ranks.length > 0 ? (
            profile.ranks.map((r) => <RankCard key={r.queue} rank={r} />)
          ) : profile.plays_on ? null : (
            <RankCard
              rank={{
                queue: 'RANKED_SOLO_5x5',
                queue_label: 'Ranked Solo/Duo',
                tier: null,
                division: null,
                league_points: 0,
                wins: 0,
                losses: 0,
                win_rate: 0,
                games: 0,
                hot_streak: false,
                inactive: false,
                numeric_rank: 0,
              }}
            />
          )}

          <AnalyticsPanel platform={platform} name={name} tag={tag} />

          {pool.length > 0 && (
            <section className="rounded-sm border border-line bg-panel">
              <header className="border-b border-line-soft px-4 py-2.5">
                <h2 className="display text-sm font-600 text-ink-dim">
                  Most played, last {matches.length} games
                </h2>
              </header>
              <ul className="divide-y divide-line-soft">
                {pool.map((c) => (
                  <li key={c.id} className="flex items-center gap-2.5 px-4 py-2">
                    {c.icon && (
                      <img src={c.icon} alt="" className="size-8 rounded-sm" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="display truncate text-[15px] font-600 text-ink">
                        {c.name}
                      </p>
                      <p className="tnum text-xs text-ink-faint">
                        {c.avgKda.toFixed(2)} KDA
                      </p>
                    </div>
                    <div className="text-right">
                      <p
                        className="tnum text-sm font-600"
                        style={{ color: winRateColor(c.winRate, 0.6) }}
                      >
                        {pct(c.winRate)}
                      </p>
                      <p className="tnum text-xs text-ink-faint">{c.games}g</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>

        {/* Feed */}
        <div className="min-w-0 space-y-4">
          {matches.length > 0 && <FormStrip matches={matches} />}

          <div className="flex items-center gap-1 text-sm">
            {QUEUE_FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setQueue(f.id)}
                aria-pressed={queue === f.id}
                className={`border-b-2 px-3 pb-1.5 pt-1 font-display font-600 transition-colors ${
                  queue === f.id
                    ? 'border-gold text-gold-bright'
                    : 'border-transparent text-ink-dim hover:text-ink'
                }`}
              >
                {f.label}
              </button>
            ))}
            {matchesQuery.isFetching && !matchesQuery.isFetchingNextPage && (
              <span className="ml-auto">
                <Spinner />
              </span>
            )}
          </div>

          {matchesQuery.isLoading && <MatchListSkeleton />}

          {matchesQuery.isError && (
            <ErrorView
              error={matchesQuery.error}
              onRetry={() => matchesQuery.refetch()}
            />
          )}

          {matchesQuery.isSuccess && matches.length === 0 && (
            <EmptyState
              title="No games here"
              body="Nothing in this queue yet. Try a different filter, or check another region."
            />
          )}

          <div className="border-t border-line-soft">
            {matches.map((m) => (
              <MatchRow
                key={m.match_id}
                match={m}
                platform={platform}
                puuid={profile.puuid}
              />
            ))}
          </div>

          {matchesQuery.hasNextPage && (
            <button
              onClick={() => matchesQuery.fetchNextPage()}
              disabled={matchesQuery.isFetchingNextPage}
              className="w-full rounded-sm border border-line bg-panel py-2.5 text-sm font-500 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:opacity-60"
            >
              {matchesQuery.isFetchingNextPage
                ? 'Loading games from Riot…'
                : 'Load 20 more'}
            </button>
          )}

          {matches.length > 0 && (
            <p className="pt-1 text-xs text-ink-faint">
              {compact(matches.length)} games loaded. New games are fetched from Riot
              once, then served from storage.
            </p>
          )}
        </div>
      </div>

      <p className="mt-8 text-xs text-ink-faint">
        <Link to="/" className="hover:text-ink-dim">
          Search another player
        </Link>
      </p>
      </div>
    </div>
  )
}
