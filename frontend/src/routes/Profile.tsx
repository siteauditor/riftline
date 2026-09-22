import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'

import AnalyticsPanel from '../components/AnalyticsPanel'
import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import Crest from '../components/Crest'
import FormStrip from '../components/FormStrip'
import MatchRow from '../components/MatchRow'
import ProfileTabs from '../components/ProfileTabs'
import AddToGroup from '../components/group/AddToGroup'
import RankCard from '../components/RankCard'
import ReviewPanel from '../components/ReviewPanel'
import StrengthsPanel from '../components/StrengthsPanel'
import { EmptyState, ErrorView, MatchListSkeleton, Spinner } from '../components/StateViews'
import { api, type Analytics, type Profile as ProfileData } from '../lib/api'
import { heads } from '../lib/seo'
import { useMatchHistory } from '../lib/useMatchHistory'
import {
  compact,
  ordinal,
  pct,
  scoreColor,
  tierColor,
  tierLabel,
  timeAgo,
  winRateColor,
} from '../lib/format'
import { intParam, withParams } from '../lib/searchParams'
import { rememberSearch } from '../lib/storage'


// Riot's history filter takes one queue id. Arena is left out because Riot
// splits it across several (1700, 1710, 1750), so a chip for one would miss
// games from the others.
const QUEUE_FILTERS = [
  { id: null, label: 'All' },
  { id: 420, label: 'Solo/Duo' },
  { id: 440, label: 'Flex' },
  { id: 400, label: 'Normal' },
  { id: 480, label: 'Swiftplay' },
  { id: 450, label: 'ARAM' },
]

// The analytics endpoint's ceiling, and the key the champions tab and the
// mastery page already use, so the three share one stored-games answer.
const PLAYED_LIMIT = 1000

// Matches the server's refresh floor (REFRESH_FLOOR_SECONDS): an Update inside
// it would be answered from the cache, so the button waits it out instead of
// pretending to have fetched.
const UPDATE_COOLDOWN_MS = 60_000

// The leaderboard's page size, to link a ladder position to the right page.
const LADDER_PAGE = 50

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

/** The clock, re-read every few seconds, for labels like "updated 2m ago". */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}

export default function Profile() {
  const { platform = '', name = '', tag = '' } = useParams()
  // In the URL, so a filtered history survives a reload, a shared link, and
  // the way back from an item or another player opened out of a game.
  const [search, setSearch] = useSearchParams()
  const queue = intParam(search, 'queue', 0) || null
  const championFilter = intParam(search, 'champion', 0) || null
  const setFilter = (patch: { queue?: number | null; champion?: number | null }) =>
    setSearch((prev) => withParams(prev, patch), { replace: true })
  const queryClient = useQueryClient()

  const profileQuery = useQuery({
    queryKey: ['profile', platform, name, tag],
    queryFn: () => api.profile(platform, name, tag),
  })

  // Remembered only once Riot has answered, so a mistyped ID never becomes a
  // "recent" search. Stored with the name as Riot spells it, not as typed.
  const loaded = profileQuery.data
  useEffect(() => {
    if (!loaded?.game_name || !loaded.tag_line) return
    rememberSearch({
      platform: loaded.platform,
      gameName: loaded.game_name,
      tagLine: loaded.tag_line,
      iconUrl: loaded.profile_icon_url,
    })
  }, [loaded])

  // The live page reads the same history, so the query lives in one hook: two
  // configurations of one cache key is a race between whichever page mounts
  // first.
  const { query: matchesQuery, matches } = useMatchHistory(platform, name, tag, {
    queue,
    champion: championFilter,
    enabled: profileQuery.isSuccess,
  })
  const stored = matchesQuery.data?.pages[0]?.source === 'stored'
  const storedTotal = matchesQuery.data?.pages[0]?.stored_total ?? null

  // The champions this player has stored games on, for the champion filter.
  // Storage only, so it costs no Riot call.
  const playedQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, { queue: null, limit: PLAYED_LIMIT }],
    queryFn: () => api.analytics(platform, name, tag, { queue: null, limit: PLAYED_LIMIT }),
    enabled: profileQuery.isSuccess,
    retry: false,
  })

  // Read after the history, not beside it. The analytics describe stored games,
  // and loading history is what stores them: on a first visit, asked in
  // parallel, they described nothing. Keyed on when the history last loaded,
  // so every new page is reflected, with the previous answer held meanwhile.
  const analyticsQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, matchesQuery.dataUpdatedAt],
    queryFn: () => api.analytics(platform, name, tag),
    enabled: matchesQuery.isSuccess,
    placeholderData: keepPreviousData,
    retry: false,
  })

  // The header's art is the champion they play most, from the games we hold:
  // the subject of the page rather than a backdrop.
  const champions = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })
  const championName =
    champions.data?.champions.find((c) => c.id === championFilter)?.name ?? 'this champion'

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
  const player = { platform, name, tag }
  const topChampion = analyticsQuery.data?.champions[0]?.champion.id
  const heroArt =
    champions.data?.champions.find((c) => c.id === topChampion)?.art_url ?? null

  async function refreshAll() {
    const fresh = await api.profile(platform, name, tag, true)
    queryClient.setQueryData(['profile', platform, name, tag], fresh)
    // Prefix matches: every queue filter's history, the Champions tab's
    // analytics and both rank-history lines.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['matches', platform, name, tag] }),
      queryClient.invalidateQueries({ queryKey: ['analytics', platform, name, tag] }),
      queryClient.invalidateQueries({ queryKey: ['rank-history', platform, name, tag] }),
    ])
  }

  const ranks = profile.ranks.length > 0 ? profile.ranks : profile.plays_on ? [] : [UNRANKED_SOLO]

  return (
    <div style={{ '--accent': accent } as CSSProperties}>
      <Head
        {...heads.profile(
          profile.riot_id,
          platform,
          headline ? tierLabel(headline.tier, headline.division) : null,
        )}
      />
      {/*
        A band, not a card. The rule on the left is the subject's own rank
        colour, which is the redesign's one repeated motif: a Challenger reads
        cyan here and an Iron player grey, so the colour is telling you
        something before you have read a word.
      */}
      <ArtHeader art={heroArt}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-4">
          {profile.profile_icon_url && (
            <img
              src={profile.profile_icon_url}
              alt=""
              className="size-16 shrink-0 ring-1 ring-line"
            />
          )}
          <div className="min-w-0">
            <h1 className="display text-[clamp(1.9rem,4.5vw,3rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
              {profile.game_name}
              <span className="ml-2 text-[0.5em] font-600 text-ink-faint">
                #{profile.tag_line}
              </span>
            </h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-ink-dim">
              {headline && (
                <span className="flex items-center gap-1.5">
                  <Crest tier={headline.tier} division={headline.division} size="line" />
                  <span
                    className="display text-base font-700 uppercase tracking-wide"
                    style={{ color: accent }}
                  >
                    {tierLabel(headline.tier, headline.division)}
                  </span>
                  <span className="tnum text-ink-dim">
                    {headline.league_points.toLocaleString()} LP
                  </span>
                </span>
              )}
              {profile.ladder && <LadderChip ladder={profile.ladder} />}
              <span className="eyebrow">Level {profile.summoner_level ?? '–'}</span>
              <span className="eyebrow">{profile.platform_label}</span>
            </p>
            <div className="flex flex-wrap items-start gap-x-2.5">
              <UpdateControl updatedAt={profile.updated_at} onUpdate={refreshAll} />
              <div className="mt-1.5 text-xs">
                <AddToGroup platform={platform} riotId={profile.riot_id} />
              </div>
            </div>
          </div>

          <ProfileTabs platform={platform} name={name} tag={tag} />
        </div>
      </ArtHeader>

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

        {/*
          Source order is the phone order: a one-line rank per queue, the games,
          then the rail. On a 390x844 screen the rail used to come first and the
          first game sat 1,278px down, under the rank card, play style and most
          played. The header already carries the tier and LP, so on a phone the
          full cards (with the LP line) wait below the games, and on wide
          screens the grid puts the rail back on the left.
        */}
        <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
          {ranks.length > 0 && (
            <div className="space-y-1.5 lg:hidden">
              {ranks.map((r) => (
                <RankCard key={r.queue} rank={r} compact />
              ))}
            </div>
          )}

          {/* Feed */}
          <div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">
            {matches.length > 0 && <FormStrip matches={matches} />}

            {analyticsQuery.data && (
              <StrengthsPanel profiles={analyticsQuery.data.score_profile} />
            )}

            <div className="flex flex-wrap items-center gap-x-1 gap-y-2 text-sm">
              {QUEUE_FILTERS.map((f) => (
                <button
                  key={f.label}
                  onClick={() => setFilter({ queue: f.id })}
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
              <label className="ml-auto flex items-center gap-2">
                <span className="text-xs text-ink-faint">Champion</span>
                <select
                  value={championFilter ?? ''}
                  onChange={(e) => setFilter({ champion: Number(e.target.value) || null })}
                  className="control max-w-[11rem]"
                >
                  <option value="">All champions</option>
                  {/* A link can name a champion with no stored games yet. */}
                  {championFilter &&
                    !playedQuery.data?.champions.some((c) => c.champion.id === championFilter) && (
                      <option value={championFilter}>{championName}</option>
                    )}
                  {(playedQuery.data?.champions ?? []).map((c) => (
                    <option key={c.champion.id} value={c.champion.id}>
                      {c.champion.name} ({c.games})
                    </option>
                  ))}
                </select>
              </label>
              {matchesQuery.isFetching && !matchesQuery.isFetchingNextPage && <Spinner />}
            </div>

            {championFilter && stored && storedTotal !== null && (
              <p className="border-l-2 border-gold/50 py-1 pl-3 text-xs leading-relaxed text-ink-dim">
                {storedTotal.toLocaleString()} {championName} {storedTotal === 1 ? 'game' : 'games'}{' '}
                we hold{queue ? ` in ${QUEUE_FILTERS.find((f) => f.id === queue)?.label ?? 'this queue'}` : ''}.
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

            {matchesQuery.isLoading && <MatchListSkeleton />}

            {matchesQuery.isError && (
              <ErrorView
                error={matchesQuery.error}
                onRetry={() => matchesQuery.refetch()}
              />
            )}

            {matchesQuery.isSuccess && matches.length === 0 && (
              <EmptyState
                title={championFilter ? `No stored ${championName} games here` : 'No games here'}
                body={
                  championFilter
                    ? 'Nothing stored for this champion in this queue. Load more history under All champions, or pick another queue.'
                    : 'Nothing in this queue yet. Try a different filter, or check another region.'
                }
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
                className="w-full frame py-2.5 text-sm font-500 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:opacity-60"
              >
                {matchesQuery.isFetchingNextPage
                  ? stored
                    ? 'Loading…'
                    : 'Loading games from Riot…'
                  : stored
                    ? 'Show 20 more'
                    : 'Load 20 more'}
              </button>
            )}

            {matches.length > 0 && (
              <p className="pt-1 text-xs text-ink-faint">
                {stored && storedTotal !== null
                  ? `${compact(matches.length)} of ${compact(storedTotal)} shown, all from storage.`
                  : `${compact(matches.length)} games loaded. New games are fetched from Riot once, then served from storage.`}
              </p>
            )}
          </div>

          {/* Rail */}
          <aside className="space-y-4 lg:sticky lg:top-20 lg:col-start-1 lg:row-start-1 lg:self-start">
            {ranks.map((r) => (
              <RankCard key={r.queue} rank={r} player={r.tier ? player : undefined} />
            ))}
            <AnalyticsPanel data={analyticsQuery.data} />
            <ReviewPanel review={analyticsQuery.data?.review} lanes={analyticsQuery.data?.lanes} />
            {analyticsQuery.data && (
              <MostPlayed
                analytics={analyticsQuery.data}
                championsPath={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}/champions`}
              />
            )}
          </aside>
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

/** "#257 EUW": where they stand on the stored solo ladder of their shard. */
function LadderChip({ ladder }: { ladder: NonNullable<ProfileData['ladder']> }) {
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
      ? `#${ladder.position.toLocaleString()} ${ladder.platform_label}`
      : `#${ladder.tier_position.toLocaleString()} in ${tier}`
  const title =
    (ladder.position !== null
      ? `${ordinal(ladder.position)} on the ${ladder.platform_label} solo ladder, ` +
        `${ordinal(ladder.tier_position)} in ${tier}. `
      : `${ordinal(ladder.tier_position)} in ${tier} on ${ladder.platform_label}. `) +
    `From the ladder as it stood ${timeAgo(ladder.as_of)}.`
  return (
    <Link
      to={`/leaderboards?${params.toString()}`}
      title={title}
      className="tnum rounded-sm bg-raised px-1.5 py-0.5 text-xs font-600 text-ink transition-colors hover:text-gold-bright"
    >
      {label}
    </Link>
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
  const now = useNow(5_000)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const cooling = updatedAt !== null && now - updatedAt < UPDATE_COOLDOWN_MS

  async function run() {
    setBusy(true)
    setFailed(null)
    try {
      await onUpdate()
    } catch (error) {
      setFailed(error instanceof Error ? error.message : 'The update failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-ink-faint">
      {updatedAt !== null && (
        <span>Updated {now - updatedAt < 60_000 ? 'just now' : timeAgo(updatedAt)}</span>
      )}
      <button
        type="button"
        onClick={run}
        disabled={busy || cooling}
        className="rounded-sm border border-line px-2 py-0.5 font-600 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:cursor-default disabled:opacity-50 disabled:hover:border-line disabled:hover:text-ink-dim"
        title={cooling ? 'Riot was asked less than a minute ago.' : 'Ask Riot for the latest rank and games.'}
      >
        {busy ? 'Updating…' : 'Update'}
      </button>
      {failed && (
        <span role="alert" className="text-loss">
          {failed}
        </span>
      )}
    </p>
  )
}

/** The five most played champions over every stored game, with a way to the rest. */
function MostPlayed({
  analytics,
  championsPath,
}: {
  analytics: Analytics
  championsPath: string
}) {
  const top = analytics.champions.slice(0, 5)
  if (top.length === 0) return null
  return (
    <section className="frame">
      <header className="flex items-baseline justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">
          Most played, {analytics.games_analysed} stored games
        </h2>
      </header>
      <ul className="divide-y divide-line-soft">
        {top.map((c) => (
          <li key={c.champion.id} className="flex items-center gap-2.5 px-4 py-2">
            {c.champion.icon_url && (
              <img src={c.champion.icon_url} alt="" className="size-8 rounded-sm" />
            )}
            <div className="min-w-0 flex-1">
              <p className="display truncate text-[15px] font-600 text-ink">
                {c.champion.name}
              </p>
              <p className="tnum text-xs text-ink-faint">
                {c.kda.toFixed(2)} KDA
                {c.avg_score !== null && (
                  <>
                    {', score '}
                    <span style={{ color: scoreColor(c.avg_score) }}>
                      {c.avg_score.toFixed(1)}
                    </span>
                  </>
                )}
              </p>
            </div>
            <div className="text-right">
              <p
                className="tnum text-sm font-600"
                style={{ color: winRateColor(c.win_rate, 0.6) }}
              >
                {pct(c.win_rate)}
              </p>
              <p className="tnum text-xs text-ink-faint">{c.games}g</p>
            </div>
          </li>
        ))}
      </ul>
      <Link
        to={championsPath}
        className="block border-t border-line-soft px-4 py-2 text-xs text-ink-dim transition-colors hover:text-gold-bright"
      >
        All {analytics.champions.length} champions
      </Link>
    </section>
  )
}
