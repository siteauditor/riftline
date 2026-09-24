import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import AnalyticsPanel from '../components/AnalyticsPanel'
import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import Crest from '../components/Crest'
import FormStrip from '../components/FormStrip'
import MatchRow from '../components/MatchRow'
import ProfileTabs from '../components/ProfileTabs'
import AddToGroup from '../components/group/AddToGroup'
import RankCard from '../components/RankCard'
import SelectField from '../components/SelectField'
import { Button } from '@/components/ui/button'
import ReviewPanel from '../components/ReviewPanel'
import StrengthsPanel from '../components/StrengthsPanel'
import { EmptyState, ErrorView, MatchListSkeleton, ProfileSkeleton, Spinner } from '../components/StateViews'
import { api, type Analytics, type Profile as ProfileData } from '../lib/api'
import { useNow } from '../lib/clock'
import { profileSummary } from '../lib/prose'
import { queries } from '../lib/queries'
import { canonicalPlatform, movedFrom, profileRedirect, summonerPath } from '../lib/profileAddress'
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
import { intParam, useHydrated, useHydratedSearchParams, withParams } from '../lib/searchParams'
import { rememberSearch } from '../lib/storage'
import { Chip, ChipGroup } from '@/components/ui/chips'
import Hint from '../components/Hint'


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

// The champion filter's "any" choice needs a word: Radix refuses an empty item value.
const ALL_CHAMPIONS = 'all'

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
  const queue = intParam(search, 'queue', 0) || null
  const championFilter = intParam(search, 'champion', 0) || null
  const setFilter = (patch: { queue?: number | null; champion?: number | null }) =>
    setSearch((prev) => withParams(prev, patch), { replace: true })
  const queryClient = useQueryClient()

  // A prerendered profile carries the answers storage gave the prerenderer,
  // under keys of their own (`queries.*Stored`). Each live query shows that
  // answer as its placeholder: the page is complete on first render, the
  // same on the server and in the browser, and moves to Riot's fresher
  // answer when it arrives. A profile that was not prerendered has no such
  // entries and loads as it always did.
  const profileQuery = useQuery({
    ...queries.profile(platform, name, tag),
    placeholderData: () =>
      queryClient.getQueryData(queries.profileStored(platform, name, tag).queryKey),
  })

  // Riot's answer, not the stored one standing in for it.
  const live = profileQuery.isPlaceholderData ? undefined : profileQuery.data
  const hydrated = useHydrated()
  const location = useLocation()
  const navigate = useNavigate()

  // Remembered only once Riot has answered, so a mistyped ID never becomes a
  // "recent" search: the stored answer a prerendered page opens with is not
  // one. Stored with the name as Riot spells it, not as typed, and under the
  // address the page settles on.
  useEffect(() => {
    if (!live?.game_name || !live.tag_line) return
    rememberSearch({
      platform: canonicalPlatform(live),
      gameName: live.game_name,
      tagLine: live.tag_line,
      iconUrl: live.profile_icon_url,
    })
  }, [live])

  // One address per player. A shard the account holds nothing on moves to
  // its home (a view of NA for a EUW player used to be the page that deleted
  // their rank), and an alias or another spelling moves to the canonical
  // address. After hydration, so a prerendered page hydrates as the HTML it
  // was served, and on Riot's answer only. The answer is seeded under the new
  // address, so the page there does not ask again.
  useEffect(() => {
    if (!hydrated || !live) return
    const move = profileRedirect({
      params: { platform, name, tag },
      search: location.search,
      profile: live,
      state: location.state,
    })
    if (!move) return
    const { seed } = move
    queryClient.setQueryData(queries.profile(seed.platform, seed.name, seed.tag).queryKey, seed.profile)
    navigate(move.to, { replace: true, state: move.state })
  }, [hydrated, live, platform, name, tag, location.search, location.state, queryClient, navigate])
  // History state is the browser's alone, so it is read once the page is hydrated.
  const movedFromLabel = hydrated ? movedFrom(location.state) : null
  // While a move is pending, nothing is asked under the address being left:
  // the history of a view of NA was fetched twice, once there and once at
  // the EUW address it moved to.
  const moving =
    hydrated &&
    live !== undefined &&
    profileRedirect({ params: { platform, name, tag }, search: location.search, profile: live, state: location.state }) !== null

  // The live page reads the same history, so the query lives in one hook: two
  // configurations of one cache key is a race between whichever page mounts
  // first.
  const { query: matchesQuery, matches } = useMatchHistory(platform, name, tag, {
    queue,
    champion: championFilter,
    enabled: profileQuery.isSuccess && !moving,
    // The stored page is the unfiltered one.
    placeholder:
      queue === null && championFilter === null
        ? () => queryClient.getQueryData(queries.matchesStored(platform, name, tag).queryKey)
        : undefined,
  })
  const stored = matchesQuery.data?.pages[0]?.source === 'stored'
  const storedTotal = matchesQuery.data?.pages[0]?.stored_total ?? null

  // As with the header: when the live history fails on a prerendered page,
  // the stored games it was rendered with stay on screen under a line that
  // says so, rather than an error where the games were. Only for the
  // unfiltered list, which is the one that was stored.
  const storedPage =
    matchesQuery.isError && matches.length === 0 && queue === null && championFilter === null
      ? queryClient.getQueryData(queries.matchesStored(platform, name, tag).queryKey)
      : undefined
  const rows = storedPage?.matches ?? matches

  // The champions this player has stored games on, for the champion filter.
  // Storage only, so it costs no Riot call.
  const playedQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, { queue: null, limit: PLAYED_LIMIT }],
    queryFn: () => api.analytics(platform, name, tag, { queue: null, limit: PLAYED_LIMIT }),
    enabled: profileQuery.isSuccess && !moving,
    retry: false,
  })

  // Read after the history, not beside it. The analytics describe stored games,
  // and loading history is what stores them: on a first visit, asked in
  // parallel, they described nothing. Keyed on when the history last loaded,
  // so every new page is reflected, with the previous answer held meanwhile.
  //
  // Not while the history is still the placeholder: that would describe the
  // stored games before the live page has been stored, and ask again a
  // moment later. The stored analytics stand in until then.
  const analyticsQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, matchesQuery.dataUpdatedAt],
    queryFn: () => api.analytics(platform, name, tag),
    enabled: matchesQuery.isSuccess && !matchesQuery.isPlaceholderData,
    placeholderData: (previous) =>
      previous ?? queryClient.getQueryData(queries.analyticsStored(platform, name, tag).queryKey),
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
      <>
        <Head {...heads.profile(`${name}#${tag}`, platform)} />
        <ProfileSkeleton />
      </>
    )
  }

  // The stored answer a prerendered page carries outlives a failed live
  // fetch: Riot being down, or a key that has expired, is worth a line over
  // the page, not a blank page over data we hold.
  const storedProfile = queryClient.getQueryData(queries.profileStored(platform, name, tag).queryKey)
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
  const topChampion = analyticsQuery.data?.champions[0]?.champion.id
  const heroArt =
    champions.data?.champions.find((c) => c.id === topChampion)?.art_url ?? null

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
  const summary = profileSummary(profile, analyticsQuery.data)

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
                    {headline.league_points.toLocaleString('en-US')} LP
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
        {profileQuery.isError && !profileQuery.data && (
          <p className="accent-edge mb-5 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
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
          <p className="accent-edge mb-5 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
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
          <p className="accent-edge mb-5 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
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
          <p className="accent-edge mb-5 py-2 pl-4 text-sm leading-relaxed text-ink-dim">
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
            {/* The page in sentences, from its own numbers: for a reader who
                does not know the game, and for anything that reads the page
                without a browser. */}
            <section
              aria-label={`${profile.riot_id} in brief`}
              className="max-w-prose space-y-1.5 text-sm leading-relaxed text-ink-dim"
            >
              {summary.map((sentence, i) => (
                <p key={i} className={i === 0 ? 'text-ink' : undefined}>
                  {sentence}
                </p>
              ))}
            </section>

            {matches.length > 0 && <FormStrip matches={matches} />}

            {analyticsQuery.data && (
              <StrengthsPanel profiles={analyticsQuery.data.score_profile} />
            )}

            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
              <ChipGroup label="Queue">
                {QUEUE_FILTERS.map((f) => (
                  <Chip key={f.label} active={queue === f.id} onClick={() => setFilter({ queue: f.id })}>
                    {f.label}
                  </Chip>
                ))}
              </ChipGroup>
              <SelectField
                label="Champion"
                className="ml-auto"
                value={championFilter ? String(championFilter) : ALL_CHAMPIONS}
                onValueChange={(v) => setFilter({ champion: v === ALL_CHAMPIONS ? null : Number(v) })}
                triggerClassName="max-w-[11rem]"
                options={[
                  { value: ALL_CHAMPIONS, label: 'All champions' },
                  // A link can name a champion with no stored games yet.
                  ...(championFilter &&
                  !playedQuery.data?.champions.some((c) => c.champion.id === championFilter)
                    ? [{ value: String(championFilter), label: championName }]
                    : []),
                  ...(playedQuery.data?.champions ?? []).map((c) => ({
                    value: String(c.champion.id),
                    label: `${c.champion.name} (${c.games})`,
                  })),
                ]}
              />
              {matchesQuery.isFetching && !matchesQuery.isFetchingNextPage && <Spinner />}
            </div>

            {championFilter && stored && storedTotal !== null && (
              <p className="border-l-2 border-gold/50 py-1 pl-3 text-xs leading-relaxed text-ink-dim">
                {storedTotal.toLocaleString('en-US')} {championName} {storedTotal === 1 ? 'game' : 'games'}{' '}
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
                title={championFilter ? `No stored ${championName} games here` : 'No games here'}
                body={
                  championFilter
                    ? 'Nothing stored for this champion in this queue. Load more history under All champions, or pick another queue.'
                    : 'Nothing in this queue yet. Try a different filter, or check another region.'
                }
              />
            )}

            <div className="border-t border-line-soft">
              {rows.map((m) => (
                <MatchRow
                  key={m.match_id}
                  match={m}
                  platform={platform}
                  puuid={profile.puuid}
                />
              ))}
            </div>

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
                championsPath={summonerPath(platform, name, tag, 'champions')}
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
      setFailed(error instanceof Error ? error.message : 'The update failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs text-ink-faint">
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
