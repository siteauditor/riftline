import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import ProfileTabs from '../components/ProfileTabs'
import BandSection from '../components/mastery/BandSection'
import ChampionDetail from '../components/mastery/ChampionDetail'
import { buildPool, type PoolChampion } from '../components/mastery/pool'
import { LEGEND_STEPS } from '../components/mastery/scale'
import { Stat, StatCell, StatStrip } from '../components/Stat'
import { EmptyState, ErrorView, GridSkeleton } from '../components/StateViews'
import { api } from '../lib/api'
import { heads } from '../lib/seo'
import { compact, pct, timeAgo } from '../lib/format'
import { foldName, useHydratedSearchParams, useSearchText, withParams } from '../lib/searchParams'
import { useChampionArt } from '../lib/useChampionArt'
import CountUp from '../components/CountUp'

/** The analytics ceiling the champions tab already asks for. Same key, same
 *  options, so the two pages share one cache entry and one request. */
const ANALYTICS_LIMIT = 1000

export default function Mastery() {
  const { platform = '', name = '', tag = '' } = useParams()
  // In the URL, so the filter survives opening a champion and coming back.
  const [search, setSearch] = useHydratedSearchParams()
  const [query, setQuery] = useSearchText('q', 120)
  const recentOnly = search.get('recent') === '1'
  const setRecentOnly = (on: boolean) =>
    setSearch((prev) => withParams(prev, { recent: on }), { replace: true })
  const [selected, setSelected] = useState<number | null>(null)
  // One reading, taken when the page mounts, so the bands and the filter cannot
  // disagree about where "the last 30 days" starts mid render.
  const [now] = useState(() => Date.now())
  // Folded, so "kaisa" finds Kai'Sa as it does on the tier list.
  const filter = foldName(query)

  const masteryQuery = useQuery({
    queryKey: ['mastery', platform, name, tag],
    queryFn: () => api.mastery(platform, name, tag),
  })
  const championsQuery = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })
  // What our own stored games say about these champions. Storage only, so it
  // costs no Riot call, and it is never allowed to block the page: a player
  // with nothing stored is the normal first visit.
  const recordsQuery = useQuery({
    queryKey: ['analytics', platform, name, tag, { queue: null, limit: ANALYTICS_LIMIT }],
    queryFn: () => api.analytics(platform, name, tag, { queue: null, limit: ANALYTICS_LIMIT }),
    retry: false,
  })

  const pool = useMemo(
    () =>
      buildPool({
        mastery: masteryQuery.data,
        champions: championsQuery.data?.champions ?? [],
        records: recordsQuery.data?.champions ?? [],
        now,
      }),
    [masteryQuery.data, championsQuery.data, recordsQuery.data, now],
  )

  // Their deepest champion, which is what this page is about. Read before the
  // loading and error branches, because a hook cannot run only sometimes.
  const heroArt = useChampionArt(pool.top?.id)

  const shown = useMemo(() => {
    const recentSince = now - 30 * 86_400_000
    return pool.champions.filter(
      (c) =>
        (!filter || foldName(c.name).includes(filter)) &&
        (!recentOnly || (c.lastPlayed !== null && c.lastPlayed >= recentSince)),
    )
  }, [pool.champions, filter, recentOnly, now])
  const shownIds = useMemo(() => new Set(shown.map((c) => c.id)), [shown])
  const inBand = (band: PoolChampion[]) => band.filter((c) => shownIds.has(c.id))

  const header = (
    <ArtHeader art={heroArt}>
      <Head {...heads.profileTab(`${name}#${tag}`, platform, 'mastery')} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="min-w-0">
          <p className="eyebrow">Champion mastery</p>
          <h1 className="display mt-1 text-[clamp(1.9rem,4.5vw,2.9rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
            {name}
            <span className="ml-2 text-[0.5em] font-600 text-ink-faint">#{tag}</span>
          </h1>
        </div>
        <ProfileTabs platform={platform} name={name} tag={tag} />
      </div>
    </ArtHeader>
  )

  if (masteryQuery.isLoading || championsQuery.isLoading) {
    return (
      <div>
        {header}
        <div className="mx-auto max-w-[1280px] px-4 py-6">
          <GridSkeleton items={12} />
        </div>
      </div>
    )
  }

  if (masteryQuery.isError) {
    return (
      <div>
        {header}
        <div className="mx-auto max-w-[1280px] px-4 py-10">
          <ErrorView
            error={masteryQuery.error}
            context={`${name}#${tag}`}
            onRetry={() => masteryQuery.refetch()}
          />
        </div>
      </div>
    )
  }

  const mastery = masteryQuery.data
  const base = `/summoner/${encodeURIComponent(platform)}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`
  const selectedChampion = pool.champions.find((c) => c.id === selected) ?? null

  // Riot keeps mastery per shard and answers 200 with an empty list on the
  // wrong one, which used to render as 173 grey squares and three zeroes.
  if (pool.played === 0) {
    return (
      <div>
        {header}
        <div className="mx-auto max-w-[1280px] px-4 py-10">
          <EmptyState
            title="No mastery to show"
            body="Riot returned no champion mastery for this account on this region. Mastery is kept per region, so an account that plays somewhere else reads as empty here."
          />
        </div>
      </div>
    )
  }

  return (
    <div>
      {header}

      <div className="mx-auto max-w-[1280px] px-4 py-6">
        <StatStrip>
          <StatCell>
            <Stat
              label="Mastery points"
              value={<CountUp value={pool.totalPoints} format={compact} />}
              sub={`on ${pool.played} champions`}
              title="Every mastery point Riot records for this account, over its whole life."
            />
          </StatCell>
          <StatCell>
            <Stat
              label="Core pool"
              value={<CountUp value={pool.bands.core.champions.length} />}
              sub="hold half the points"
              title="The fewest champions that together hold the first half of their mastery points."
            />
          </StatCell>
          <StatCell>
            <Stat
              label="Top champion"
              value={pool.top ? <CountUp value={pool.top.share} format={(n) => pct(n)} /> : '-'}
              sub={pool.top ? `${pool.top.name}, ${compact(pool.top.points)} points` : undefined}
              title="Share of their mastery points that sits on one champion."
            />
          </StatCell>
          <StatCell>
            <Stat
              label="Played this month"
              value={<CountUp value={pool.recent} />}
              sub={`of ${pool.played} champions`}
              title="Champions with a game in the last 30 days, by the last played time Riot reports."
            />
          </StatCell>
          <StatCell>
            <Stat
              label="Deepest level"
              value={pool.deepest ? String(pool.deepest.level) : '-'}
              sub={pool.deepest?.name}
              title="Their highest mastery level. Riot removed the level 7 cap in 2024, so there is no top."
            />
          </StatCell>
        </StatStrip>

        <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-3 border-y border-line-soft py-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-xs text-ink-faint">Find</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a champion name"
              className="control h-8 w-48 text-sm placeholder:text-ink-faint"
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-ink-dim">
            <input
              type="checkbox"
              checked={recentOnly}
              onChange={(e) => setRecentOnly(e.target.checked)}
              className="size-3.5 accent-[var(--color-gold)]"
            />
            Played in the last 30 days
          </label>
          <span className="ml-auto text-xs text-ink-faint">
            {filter || recentOnly
              ? `${shown.length} of ${pool.roster} shown`
              : `${pool.roster} champions`}
          </span>
        </div>

        {shown.length === 0 ? (
          <p className="mt-6 text-sm text-ink-faint">
            No champion matches {filter ? `"${query.trim()}"` : 'that filter'}.{' '}
            <button
              type="button"
              onClick={() => {
                setQuery('')
                setRecentOnly(false)
              }}
              className="underline decoration-line underline-offset-2 hover:text-gold-bright"
            >
              Clear it
            </button>
          </p>
        ) : (
          <div className="mt-6 space-y-7">
            <BandSection
              band={pool.bands.core}
              champions={inBand(pool.bands.core.champions)}
              size="core"
              eyebrow="First half of their points"
              title="Core pool"
              aside={bandAside(pool.bands.core.champions, inBand(pool.bands.core.champions), pool.bands.core.share)}
              selectedId={selected}
              onSelect={(c) => setSelected(c.id)}
            />
            <BandSection
              band={pool.bands.middle}
              champions={inBand(pool.bands.middle.champions)}
              size="middle"
              eyebrow="From half to 85%"
              title="Middle pool"
              aside={bandAside(pool.bands.middle.champions, inBand(pool.bands.middle.champions), pool.bands.middle.share)}
              selectedId={selected}
              onSelect={(c) => setSelected(c.id)}
              gap={6}
            />
            <BandSection
              band={pool.bands.tail}
              champions={inBand(pool.bands.tail.champions)}
              size="tail"
              eyebrow="The last 15%"
              title="Long tail"
              aside={bandAside(pool.bands.tail.champions, inBand(pool.bands.tail.champions), pool.bands.tail.share)}
              selectedId={selected}
              onSelect={(c) => setSelected(c.id)}
              gap={4}
            />
            <BandSection
              band={pool.bands.unplayed}
              champions={inBand(pool.bands.unplayed.champions)}
              size="tail"
              eyebrow="Never picked"
              title="Not played"
              aside={
                <span className="text-sm text-ink-dim">
                  {pool.bands.unplayed.champions.length} of {pool.roster}
                </span>
              }
              selectedId={selected}
              onSelect={(c) => setSelected(c.id)}
              collapsible
              gap={4}
            />
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-faint">
          <span>Mastery level</span>
          {LEGEND_STEPS.map((step) => (
            <span key={step.label} className="flex items-center gap-1.5">
              <span className="size-3" style={{ background: step.color }} aria-hidden />
              {step.label}
            </span>
          ))}
          {pool.held > 0 && (
            <span className="flex items-center gap-1.5">
              <span className="size-3 bg-accent-bright" aria-hidden />
              We hold games for this one
            </span>
          )}
        </div>

        <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-faint">
          {pool.held > 0 && (
            <>
              We hold stored games for {pool.held} of {pool.played} champions, and for{' '}
              {pool.heldInCore} of the {pool.bands.core.champions.length} in the core pool. The
              teal mark shows which.{' '}
            </>
          )}
          {pool.unknown.length > 0 && (
            <>
              {pool.unknown.length === 1 ? 'One champion here is' : `${pool.unknown.length} champions here are`}{' '}
              new to us: Riot returned{' '}
              {pool.unknown.length === 1 ? 'it' : 'them'} and our champion list does not have{' '}
              {pool.unknown.length === 1 ? 'it' : 'them'} yet.{' '}
            </>
          )}
          Mastery points are Riot's own lifetime count.
          {mastery?.platform && ` Read from ${mastery.platform.toUpperCase()}.`}
          {mastery?.fetched_at ? ` Last checked ${timeAgo(mastery.fetched_at)}.` : ''}
        </p>
      </div>

      {selectedChampion && (
        <ChampionDetail
          champion={selectedChampion}
          base={base}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}

/** The count and the share, or "3 of 7 shown" while a filter is on. */
function bandAside(all: PoolChampion[], shown: PoolChampion[], share: number) {
  if (shown.length !== all.length) {
    return (
      <span className="text-sm text-ink-dim">
        {shown.length} of {all.length} shown
      </span>
    )
  }
  return (
    <span className="text-sm text-ink-dim">
      {all.length} {all.length === 1 ? 'champion' : 'champions'}, {pct(share)} of their points
    </span>
  )
}
