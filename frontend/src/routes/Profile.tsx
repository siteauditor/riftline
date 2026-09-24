import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import AnalyticsPanel from '../components/AnalyticsPanel'
import Head from '../components/Head'
import FormStrip from '../components/FormStrip'
import MatchRow from '../components/MatchRow'
import RankCard from '../components/RankCard'
import { Button } from '@/components/ui/button'
import ReviewPanel from '../components/ReviewPanel'
import StrengthsPanel from '../components/StrengthsPanel'
import { EmptyState, ErrorView, MatchListSkeleton, ProfileSkeleton, Spinner } from '../components/StateViews'
import MostPlayed from '../components/profile/MostPlayed'
import ProfileBrief from '../components/profile/ProfileBrief'
import ProfileHeader from '../components/profile/ProfileHeader'
import QueueFilter from '../components/profile/QueueFilter'
import { api } from '../lib/api'
import { profileSummary } from '../lib/prose'
import { queries } from '../lib/queries'
import { canonicalPlatform, summonerPath } from '../lib/profileAddress'
import { heads } from '../lib/seo'
import { useChampionArt } from '../lib/useChampionArt'
import { useProfileData } from '../lib/useProfileData'
import { compact, tierColor, tierLabel } from '../lib/format'
import { intParam, useHydratedSearchParams, withParams } from '../lib/searchParams'
import {
  DEFAULT_SCOPE,
  type QueueScope,
  SCOPES,
  scopeNoun,
  scopeParam,
  useScope,
} from '../lib/profileScope'

const UNRANKED_SOLO = {
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
}

export default function Profile() {
  const { platform = '', name = '', tag = '' } = useParams()
  // In the URL, so a filtered history survives a reload, a shared link, and
  // the way back from an item or another player opened out of a game.
  const [search, setSearch] = useHydratedSearchParams()
  // One scope for the games and every number beside them: ranked unless the
  // URL says otherwise (`profileScope.ts`).
  const scope = useScope()
  const championFilter = intParam(search, 'champion', 0) || null
  const setFilter = (patch: { scope?: QueueScope; champion?: number | null }) =>
    setSearch(
      (prev) =>
        withParams(prev, {
          ...('scope' in patch ? { queue: scopeParam(patch.scope ?? DEFAULT_SCOPE) } : {}),
          ...('champion' in patch ? { champion: patch.champion } : {}),
        }),
      { replace: true },
    )
  const queryClient = useQueryClient()
  const {
    profileQuery,
    storedMode,
    storedProfile,
    storedProfilePending,
    movedFromLabel,
    matchesQuery,
    matches,
    rows,
    storedList: stored,
    storedTotal,
    storedPage,
    analytics,
  } = useProfileData(platform, name, tag, { scope, champion: championFilter })
  const scopeLabel = SCOPES.find((s) => s.id === scope)?.label ?? 'Ranked'

  // A bar of the form strip asks the row below to open (`MatchRow`).
  const [openRequest, setOpenRequest] = useState<{ matchId: string; at: number } | null>(null)

  // The static champion list, for the filtered champion's name. Prefetched by
  // the route, so the header's art below is in a prerendered page's HTML.
  const champions = useQuery({ ...queries.champions(), staleTime: 6 * 60 * 60 * 1000 })
  // The header's art is the champion they play most, from the games we hold:
  // the subject of the page rather than a backdrop.
  const heroArt = useChampionArt(analytics?.champions[0]?.champion.id)
  const championName =
    champions.data?.champions.find((c) => c.id === championFilter)?.name ?? 'this champion'

  if (profileQuery.isPending || (storedMode && !profileQuery.data && storedProfilePending)) {
    return (
      <>
        <Head {...heads.profile(`${name}#${tag}`, platform)} />
        <ProfileSkeleton />
      </>
    )
  }

  // The stored answer outlives a failed live fetch: Riot being down, or a key
  // that has expired, is worth a line over the page, not a blank page over
  // data we hold.
  if (profileQuery.isError && !storedProfile) {
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

  const profile = (profileQuery.data ?? storedProfile)!

  // The page takes its colour from this player's rank. Solo queue first,
  // because that is the rank people mean when they say "my rank".
  const headline = profile.ranks.find((r) => r.tier) ?? null
  const accent = tierColor(headline?.tier)
  const player = { platform, name, tag }

  async function refreshAll() {
    const fresh = await api.profile(platform, name, tag, { refresh: true })
    queryClient.setQueryData(queries.profile(platform, name, tag).queryKey, fresh)
    // Prefix matches: every queue filter's history, the Champions tab's
    // analytics and both rank-history lines.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['matches', platform, name, tag] }),
      queryClient.invalidateQueries({ queryKey: ['analytics', platform, name, tag] }),
      queryClient.invalidateQueries({ queryKey: ['rank-history', platform, name, tag] }),
    ])
  }

  // The ranks shown are always of the shard the page is about, so none means
  // unranked there, including on an answer for the home of a shard the
  // account never played on.
  const ranks = profile.ranks.length > 0 ? profile.ranks : [UNRANKED_SOLO]
  const riotName = profile.game_name ?? name
  const riotTag = profile.tag_line ?? tag
  const summary = profileSummary(profile, analytics)

  return (
    <div style={{ '--accent': accent } as CSSProperties}>
      <Head
        {...heads.profile(
          profile.riot_id,
          canonicalPlatform(profile),
          headline ? tierLabel(headline.tier, headline.division) : null,
          summary[0],
        )}
      />
      <ProfileHeader
        profile={profile}
        art={heroArt}
        platform={platform}
        name={name}
        tag={tag}
        scope={scope}
        onUpdate={refreshAll}
      />

      <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-4 sm:pt-6">
        {storedMode && (
          <p className="accent-edge mb-4 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
            <span className="text-ink">Live data is unavailable right now.</span> This is the
            profile as Riftline last stored it.{' '}
            <button
              type="button"
              onClick={() => profileQuery.refetch()}
              className="underline decoration-line underline-offset-2 hover:text-gold-bright"
            >
              Try again
            </button>
          </p>
        )}

        {movedFromLabel && profile.shard !== 'absent' && (
          <p className="accent-edge mb-4 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
            <span className="text-ink">
              {profile.riot_id} plays on {profile.platform_label}.
            </span>{' '}
            They have no rank and no games on {movedFromLabel}, so this is their{' '}
            {profile.platform_label} profile.
          </p>
        )}

        {/* The answer for a shard the account holds nothing on is its home's,
            and the page moves there once it has hydrated. This line is what
            shows until then, or instead when the home itself answered so. */}
        {profile.shard === 'absent' && (
          <p className="accent-edge mb-4 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
            <span className="text-ink">
              {profile.riot_id} has no rank and no games on {profile.platform_label}.
            </span>{' '}
            They play on {profile.home_platform_label}, and everything here is from there.{' '}
            <Link
              to={summonerPath(profile.home_platform, riotName, riotTag)}
              className="border-b border-gold/60 text-gold-bright transition-colors hover:border-gold-bright"
            >
              Open their {profile.home_platform_label} profile
            </Link>
          </p>
        )}

        {profile.shard === 'second' && (
          <p className="accent-edge mb-4 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
            <span className="text-ink">
              {profile.riot_id} plays mainly on {profile.home_platform_label}.
            </span>{' '}
            This page shows their {profile.platform_label} rank and games.{' '}
            <Link
              to={summonerPath(profile.home_platform, riotName, riotTag)}
              className="border-b border-gold/60 text-gold-bright transition-colors hover:border-gold-bright"
            >
              Open their {profile.home_platform_label} profile
            </Link>
          </p>
        )}

        {/*
          Games first. Source order is the phone's: the form strip, the
          filters and the games, then the rail's panels, then the page in
          sentences. On a 412x839 phone the first game sat at 1,128px, under a
          tall header, one rank card per queue, four sentences and the
          strengths panel (2026-09-24). On wide screens the grid puts the rail
          on the left, and it no longer sticks: at 1,407px tall it never showed
          its lower panels while the games scrolled.
        */}
        <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
          <div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">
            {matches.length > 0 && (
              <FormStrip
                matches={matches}
                scope={scope}
                onPick={(matchId) => setOpenRequest({ matchId, at: Date.now() })}
              />
            )}

            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <QueueFilter
                  scope={scope}
                  onScope={(next) => setFilter({ scope: next })}
                  champion={championFilter}
                  championName={championName}
                  onChampion={(next) => setFilter({ champion: next })}
                  analytics={analytics}
                />
              </div>
              {matchesQuery.isFetching && !matchesQuery.isFetchingNextPage && <Spinner />}
            </div>

            {championFilter && stored && storedTotal !== null && (
              <p className="border-l-2 border-gold/50 py-1 pl-3 text-xs leading-relaxed text-ink-dim">
                {storedTotal.toLocaleString('en-US')} {championName} {storedTotal === 1 ? 'game' : 'games'}{' '}
                we hold{scope === 'all' ? '' : ` in ${scopeLabel}`}.
                Riot cannot filter history by champion, so older games show here once more of
                the history has been loaded.{' '}
                <button
                  type="button"
                  onClick={() => setFilter({ champion: null })}
                  className="underline decoration-line underline-offset-2 hover:text-gold-bright"
                >
                  Show all champions
                </button>
              </p>
            )}

            <section aria-label="Match history" className="space-y-4">
              {matchesQuery.isPending && <MatchListSkeleton />}

              {matchesQuery.isError && !storedPage && (
                <ErrorView
                  error={matchesQuery.error}
                  onRetry={() => matchesQuery.refetch()}
                />
              )}

              {storedPage && (
                <p className="accent-edge py-2 pl-4 text-sm leading-relaxed text-ink-dim">
                  <span className="text-ink">Live history is unavailable right now.</span> These
                  are the games Riftline holds.{' '}
                  <button
                    type="button"
                    onClick={() => matchesQuery.refetch()}
                    className="underline decoration-line underline-offset-2 hover:text-gold-bright"
                  >
                    Try again
                  </button>
                </p>
              )}

              {matchesQuery.isSuccess && matches.length === 0 && (
                <EmptyState
                  title={
                    championFilter
                      ? `No stored ${championName} games here`
                      : scope === 'all'
                        ? 'No games here'
                        : `No ${scopeNoun(scope)} games here`
                  }
                  body={
                    championFilter
                      ? 'Nothing stored for this champion in these queues. Load more history under All champions, or pick another queue.'
                      : scope === 'all'
                        ? 'Riot lists no games for this player yet.'
                        : `Riot lists no ${scopeNoun(scope)} games for this player. Their other games are under All.`
                  }
                  action={
                    scope !== 'all' ? (
                      <Button variant="outline" size="sm" onClick={() => setFilter({ scope: 'all', champion: null })}>
                        Show all queues
                      </Button>
                    ) : undefined
                  }
                />
              )}

              {rows.length > 0 && (
                <div className="border-t border-line-soft">
                  {rows.map((m) => (
                    <MatchRow
                      key={m.match_id}
                      match={m}
                      platform={platform}
                      puuid={profile.puuid}
                      openRequest={openRequest?.matchId === m.match_id ? openRequest.at : 0}
                    />
                  ))}
                </div>
              )}

              {matchesQuery.hasNextPage && !matchesQuery.isPlaceholderData && (
                <Button
                  variant="outline"
                  onClick={() => matchesQuery.fetchNextPage()}
                  disabled={matchesQuery.isFetchingNextPage}
                  className="h-auto w-full py-2.5"
                >
                  {matchesQuery.isFetchingNextPage
                    ? stored
                      ? 'Loading…'
                      : 'Loading games from Riot…'
                    : stored
                      ? 'Show 20 more'
                      : 'Load 20 more'}
                </Button>
              )}

              {matches.length > 0 && (
                <p className="pt-1 text-xs text-ink-faint">
                  {stored && storedTotal !== null
                    ? `${compact(matches.length)} of ${compact(storedTotal)} shown, all from storage.`
                    : `${compact(matches.length)} games loaded. New games are fetched from Riot once, then served from storage.`}
                </p>
              )}
            </section>
          </div>

          <aside className="space-y-4 lg:col-start-1 lg:row-start-1">
            {analytics && <StrengthsPanel profiles={analytics.score_profile} layout="rail" />}
            {ranks.map((r) => (
              <RankCard key={r.queue} rank={r} player={r.tier ? player : undefined} />
            ))}
            <AnalyticsPanel data={analytics} />
            <ReviewPanel review={analytics?.review} lanes={analytics?.lanes} />
            {analytics && (
              <MostPlayed
                analytics={analytics}
                championsPath={summonerPath(platform, name, tag, 'champions')}
              />
            )}
          </aside>
        </div>

        <ProfileBrief riotId={profile.riot_id} sentences={summary} />

        <p className="mt-8 text-xs text-ink-faint">
          <Link to="/" className="hover:text-ink-dim">
            Search another player
          </Link>
        </p>
      </div>
    </div>
  )
}
