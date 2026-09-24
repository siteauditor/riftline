import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import PositionIcon from '../components/PositionIcon'
import SelectField from '../components/SelectField'
import SliceFilters, { SliceSummary, type SliceValue } from '../components/SliceFilters'
import { EmptyState, ErrorView, TableSkeleton } from '../components/StateViews'
import WinRateRange from '../components/WinRateRange'
import { type ChampionMetaRow, type MetaResponse } from '../lib/api'
import { queries, TIERLIST_MIN_GAMES } from '../lib/queries'
import { heads } from '../lib/seo'
import { compact, pct, positionLabel } from '../lib/format'
import { lowerFloor } from '../lib/minGames'
import {
  championPath,
  foldName,
  SLICE_DEFAULTS,
  sliceFromParams,
  sliceParams,
  useHydratedSearchParams,
  useSearchText,
  useSliceCorrections,
  withParams,
} from '../lib/searchParams'
import { missingTierReason, separationLine, tierLegend } from '../lib/tierlist'
import { useChampionArt } from '../lib/useChampionArt'
import Hint from '../components/Hint'
import LobbyRanks from '../components/LobbyRanks'
import { Button } from '@/components/ui/button'

/**
 * Tier badges: a ramp of treatments, not just of hues.
 *
 * Filled, tinted, solid, outlined, bare. B and C were both `raised` and differed
 * only in text colour, which is not a step a reader can see at 12px, and no
 * colour-only ramp survives a colourblind reader.
 */
const TIER_STYLE: Record<string, { bg: string; fg: string; ring?: string }> = {
  S: { bg: 'var(--color-gold)', fg: 'var(--color-deep)' },
  A: {
    bg: 'color-mix(in srgb, var(--color-gold) 26%, transparent)',
    fg: 'var(--color-gold-bright)',
  },
  B: { bg: 'var(--color-raised)', fg: 'var(--color-ink)' },
  C: { bg: 'transparent', fg: 'var(--color-ink-dim)', ring: 'var(--color-line)' },
  D: { bg: 'transparent', fg: 'var(--color-ink-faint)' },
}

const MIN_GAMES = TIERLIST_MIN_GAMES

type SortKey =
  | 'confidence_win_rate'
  | 'win_rate'
  | 'pick_rate'
  | 'ban_rate'
  | 'games'
  | 'gold'
  | 'avg_kda'
  | 'avg_cs_per_min'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'confidence_win_rate', label: 'Win rate, low end' },
  { key: 'win_rate', label: 'Raw win rate' },
  { key: 'pick_rate', label: 'Pick rate' },
  { key: 'ban_rate', label: 'Ban rate' },
  { key: 'games', label: 'Games' },
  { key: 'gold', label: 'Gold at 14' },
  { key: 'avg_kda', label: 'KDA' },
  { key: 'avg_cs_per_min', label: 'CS per minute' },
]
const DEFAULT_SORT: SortKey = 'confidence_win_rate'

const parseSort = (value: string | null): SortKey =>
  SORTS.find((s) => s.key === value)?.key ?? DEFAULT_SORT

// Champions without the figure sort last whichever way round: a missing gold
// lead is not a small one. The API leaves it out under its timeline floor.
function sortValue(row: ChampionMetaRow, key: SortKey): number | null {
  return key === 'gold' ? row.avg_gold_diff_14 : row[key]
}

export default function Tierlist() {
  // Everything that shapes the list lives in the URL. In component state it
  // was lost on the way back from a champion: pick Jungle, open Skarner, press
  // back, and the list was on All roles again (reproduced on the live site).
  const [params, setParams] = useHydratedSearchParams()
  useSliceCorrections(MIN_GAMES)
  // No bracket: the list hides "Crawled from" and describes its lobbies instead.
  const slice: SliceValue = { ...sliceFromParams(params, MIN_GAMES), bracket: null }
  const sort = parseSort(params.get('sort'))
  const [search, setSearch] = useSearchText('q')

  const updateSlice = (next: Partial<SliceValue>) =>
    setParams(
      (prev) =>
        withParams(prev, sliceParams(next), { ...SLICE_DEFAULTS, min_games: String(MIN_GAMES) }),
      { replace: true },
    )
  const setSort = (key: SortKey) =>
    setParams((prev) => withParams(prev, { sort: key }, { sort: DEFAULT_SORT }), { replace: true })

  const corpus = useQuery(queries.corpus())
  const meta = useQuery({
    ...queries.meta(slice),
    retry: false,
  })
  const position = slice.position

  // Ranked on the whole list, then filtered, so a search keeps each champion's
  // real place rather than renumbering the matches from one.
  const ranked = [...(meta.data?.rows ?? [])]
    .sort((a, b) => {
      const va = sortValue(a, sort)
      const vb = sortValue(b, sort)
      if (va === null && vb === null) return b.confidence_win_rate - a.confidence_win_rate
      if (va === null) return 1
      if (vb === null) return -1
      return vb - va
    })
    .map((row, i) => ({ row, place: i + 1 }))
  const [showAll, setShowAll] = useState(false)

  const query = foldName(search)
  const shown = query
    ? ranked.filter(({ row }) => foldName(row.champion.name).includes(query))
    : ranked
  const visible = showAll || query ? shown : shown.slice(0, FIRST_ROWS)
  const queueName = slice.queueId === 440 ? 'ranked flex' : 'ranked solo'
  const linkFor = (row: ChampionMetaRow) => championPath(row.champion, row.position, slice)
  const rows = ranked.map((r) => r.row)

  const empty = corpus.data && corpus.data.total_matches === 0
  // The art is whatever currently tops the list: the page's own subject.
  const heroArt = useChampionArt(ranked[0]?.row.champion.id)

  return (
    <div>
      <Head {...heads.tierlist(meta.data?.patch, queueName)} />
      <ArtHeader art={heroArt}>
        <p className="eyebrow">
          {meta.data
            ? `Patch ${meta.data.patch}, ${queueName}`
            : queueName.charAt(0).toUpperCase() + queueName.slice(1)}
        </p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Champion tier list
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          Ranked by the low end of the win rate each sample supports, not by raw win
          rate, and tiered within each role. A champion at 3-0 is not the strongest in
          the game, and this list doesn't pretend otherwise.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">

      {empty ? (
        <div className="mt-6">
          <EmptyState
            title="No ranked games yet"
            body="The tier list is built from the ranked games Riftline collects, and it holds none yet."
          />
        </div>
      ) : (
        <>
          <div className="mt-5">
            <SliceFilters
              value={slice}
              onChange={updateSlice}
              allowAllPositions
              hideBracket
              summary={
                meta.data && (
                  <SliceSummary
                    patch={meta.data.patch}
                    matches={meta.data.sample_matches}
                    bracket={meta.data.rank_bracket}
                  />
                )
              }
            />
          </div>

          {meta.data?.lobby_ranks && <LobbyRanks lobby={meta.data.lobby_ranks} />}

          {meta.isLoading && (
            <div className="pt-4">
              <TableSkeleton rows={12} />
            </div>
          )}

          {meta.isError && (
            <div className="mt-5">
              <ErrorView error={meta.error} onRetry={() => meta.refetch()} />
            </div>
          )}

          {meta.data?.empty_reason === 'min_games' && (
            <div className="mt-5">
              <TooFewGames data={meta.data} onMinGames={(minGames) => updateSlice({ minGames })} />
            </div>
          )}

          {rows.length > 0 && rows.every((r) => r.tier === null) && (
            <p className="mt-4 border-l-2 border-gold/50 py-1 pl-3 text-sm text-ink-dim">
              No role in this slice has enough champions with {meta.data?.tier_min_games} or
              more games to rank them against each other, so the tier column is blank. The
              numbers below are still real.
            </p>
          )}

          {meta.data && rows.length > 0 && (
            <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-faint">
              {separationLine(meta.data, rows.length)}
            </p>
          )}

          {rows.length > 0 && (
            <>
              <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
                <label className="flex min-w-0 flex-1 items-center gap-2 sm:max-w-xs">
                  <span className="sr-only">Find a champion</span>
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Find a champion"
                    spellCheck={false}
                    autoComplete="off"
                    className="control w-full"
                  />
                </label>
                <SelectField
                  label="Sort by"
                  value={sort}
                  onValueChange={(v) => setSort(v as SortKey)}
                  options={SORTS.map((s) => ({ value: s.key, label: s.label }))}
                />
                {query && (
                  <span className="text-xs text-ink-faint">
                    {shown.length} of {rows.length}
                  </span>
                )}
              </div>

              {shown.length === 0 ? (
                <p className="mt-6 text-sm text-ink-dim">
                  No champion in this slice matches &ldquo;{search}&rdquo;. It may have
                  fewer than {meta.data?.min_games} games here; lower &ldquo;min
                  games&rdquo; to include it.
                </p>
              ) : (
                <>
                  <Rows
                    rows={visible}
                    total={shown.length}
                    sort={sort}
                    onSort={setSort}
                    showRole={!position}
                    linkFor={linkFor}
                    tierFloor={meta.data?.tier_min_games ?? MIN_GAMES}
                    previousPatch={meta.data?.previous_patch ?? null}
                  />
                  {visible.length < shown.length && (
                    <Button variant="outline" size="sm" className="mt-4" onClick={() => setShowAll(true)}>
                      Show all {shown.length} picks
                    </Button>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </div>
    </div>
  )
}

/**
 * The letter, or why there is none. What a letter means is said once, on the
 * column header and in the line above the list, rather than in a hover title
 * on every badge that touch screens and keyboards never see.
 */
function TierBadge({ row, floor }: { row: ChampionMetaRow; floor: number }) {
  const tier = row.tier
  if (!tier) {
    return (
      <span className="text-ink-faint">
        <span aria-hidden>–</span>
        <span className="sr-only">{missingTierReason(row.games, floor)}</span>
      </span>
    )
  }
  const style = TIER_STYLE[tier] ?? TIER_STYLE.D
  return (
    <span
      className="inline-grid size-7 place-items-center rounded-sm font-display text-sm font-800"
      style={{
        background: style.bg,
        color: style.fg,
        boxShadow: style.ring ? `inset 0 0 0 1px ${style.ring}` : undefined,
      }}
    >
      <span className="sr-only">Tier </span>
      {tier}
    </span>
  )
}

function Gold({ row }: { row: ChampionMetaRow }) {
  const gold = row.avg_gold_diff_14
  if (gold === null) {
    return (
      <span className="text-ink-faint">
        <span aria-hidden>–</span>
        <span className="sr-only">too few games with a timeline</span>
      </span>
    )
  }
  return (
    <span className={gold >= 0 ? 'text-win' : 'text-loss'}>
      {gold >= 0 ? '+' : ''}
      {Math.round(gold).toLocaleString('en-US')}
    </span>
  )
}

/**
 * No champion clears the floor: an answer, with the way out. The API used to
 * answer 404 here with "Ingest more matches or lower min_games".
 */
function TooFewGames({ data, onMinGames }: { data: MetaResponse; onMinGames: (min: number) => void }) {
  const lower = lowerFloor(data.most_games, data.min_games)
  return (
    <EmptyState
      title={`No champion has ${data.min_games}+ games here`}
      body={
        data.most_games > 0
          ? `On patch ${data.patch} the most games any champion has in this slice is ${data.most_games}.`
          : `Riftline holds no games in this slice on patch ${data.patch} yet.`
      }
      action={
        lower !== null && (
          <Button variant="outline" size="sm" onClick={() => onMinGames(lower)}>
            Lower the minimum to {lower} games
          </Button>
        )
      }
    />
  )
}

function ChampionCell({ row, showRole }: { row: ChampionMetaRow; showRole: boolean }) {
  return (
    <span className="flex min-w-0 items-center gap-3">
      {row.champion.icon_url && (
        <img
          src={row.champion.icon_url}
          alt=""
          className="size-10 shrink-0 rounded-sm ring-1 ring-line transition-[box-shadow] group-hover:ring-gold"
          loading="lazy"
        />
      )}
      <span className="min-w-0">
        <span className="display block truncate text-[17px] font-600 text-ink transition-colors group-hover:text-gold-bright">
          {row.champion.name}
        </span>
        {showRole && (
          <span className="flex items-center gap-1 text-[11px] text-ink-faint">
            <PositionIcon position={row.position} className="size-[13px]" />
            {positionLabel(row.position)}
          </span>
        )}
      </span>
    </span>
  )
}

const COLUMNS: { key: SortKey; label: string; hint: string }[] = [
  {
    key: 'confidence_win_rate',
    label: 'Win rate',
    hint: 'Ranked by the low end of the range the sample supports',
  },
  { key: 'pick_rate', label: 'Pick', hint: 'Share of games this champion was picked in this role' },
  { key: 'ban_rate', label: 'Ban', hint: 'Share of games this champion was banned, in any role' },
  { key: 'games', label: 'Games', hint: 'Sample size' },
  { key: 'gold', label: 'Gold @14', hint: 'Average gold lead at 14 minutes, from ten or more games with a timeline' },
  { key: 'avg_kda', label: 'KDA', hint: 'Kills and assists per death' },
  { key: 'avg_cs_per_min', label: 'CS/m', hint: 'Minions and monsters per minute' },
]

// One grid for every width. Below md a row is the place, the letter, the
// champion and the range, with the secondary figures on a line beneath; from
// md the same cells become a table's columns. The page used to render a table
// for wide screens and a list of cards for phones, both in the HTML: 13,096
// DOM nodes and 1.38 MB for production's 247 rows, and 0.7 s of blocking on a
// phone while React hydrated both (measured 2026-09-24).
const GRID =
  'grid grid-cols-[1.5rem_1.75rem_minmax(0,1fr)_auto] items-center gap-x-2.5 ' +
  'md:grid-cols-[2.25rem_3rem_minmax(0,1fr)_8rem_4.5rem_4.5rem_4.5rem_5rem_3.5rem_3.5rem] md:gap-x-3'

// Rows drawn before "Show all": enough to scroll a role's whole list, few
// enough that the page stays light. A search or a role shows every match.
const FIRST_ROWS = 60

function Rows({
  rows,
  total,
  sort,
  onSort,
  showRole,
  linkFor,
  tierFloor,
  previousPatch,
}: {
  rows: { row: ChampionMetaRow; place: number }[]
  /** Every row the list holds, for the "show all" button. */
  total: number
  sort: SortKey
  onSort: (key: SortKey) => void
  showRole: boolean
  linkFor: (row: ChampionMetaRow) => string
  tierFloor: number
  previousPatch: string | null
}) {
  return (
    <div role="table" aria-label="Champion tier list" aria-rowcount={total + 1} className="mt-3">
      <div role="rowgroup" className="hidden md:block">
        <div role="row" className={`${GRID} border-b border-line py-2.5 text-xs text-ink-faint`}>
          <span role="columnheader" className="font-500">
            #
          </span>
          <span role="columnheader" className="font-500">
            <Hint text={tierLegend(tierFloor)}>
              <span
                tabIndex={0}
                className="cursor-help rounded-sm underline decoration-line decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                Tier
              </span>
            </Hint>
          </span>
          <span role="columnheader" className="font-500">
            Champion
          </span>
          {COLUMNS.map((c) => (
            <span
              key={c.key}
              role="columnheader"
              aria-sort={sort === c.key ? 'descending' : 'none'}
              className="text-right font-500"
            >
              <Hint text={c.hint}>
                <button
                  type="button"
                  onClick={() => onSort(c.key)}
                  className={`border-b-2 pb-0.5 transition-colors ${
                    sort === c.key ? 'border-gold text-gold-bright' : 'border-transparent hover:text-ink'
                  }`}
                >
                  {c.label}
                </button>
              </Hint>
            </span>
          ))}
        </div>
      </div>
      <div role="rowgroup">
        {rows.map(({ row, place }) => (
          <div
            key={`${row.champion.id}-${row.position}`}
            role="row"
            aria-rowindex={place + 1}
            className={`${GRID} lift relative border-b border-line-soft py-3 md:py-2.5`}
          >
            <span role="cell" className="tnum text-xs text-ink-faint">
              {place}
            </span>
            <span role="cell">
              <TierBadge row={row} floor={tierFloor} />
            </span>
            <span role="cell" className="min-w-0">
              {/* The whole row answers the click: the link's box is stretched
                  over it, as the phone cards were links end to end. */}
              <Link
                to={linkFor(row)}
                viewTransition
                className="group block rounded-sm outline-none after:absolute after:inset-0 focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                <ChampionCell row={row} showRole={showRole} />
              </Link>
            </span>
            <span role="cell" className="text-right">
              <WinRateRange
                rate={row.win_rate}
                low={row.confidence_win_rate}
                high={row.confidence_high}
                description={`${pct(row.win_rate, 1)} over ${row.games} games, a range of ${pct(row.confidence_win_rate, 1)} to ${pct(row.confidence_high, 1)}`}
              />
              <Trend row={row} previousPatch={previousPatch} />
            </span>
            {/* A box on a phone, the next line under the champion; from md it
                steps aside and its cells take their own columns. */}
            <div
              role="none"
              className="tnum col-span-2 col-start-3 mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-faint md:contents md:text-sm"
            >
              <span role="cell" className="md:text-right md:text-ink-dim">
                <span className="md:sr-only">Pick </span>
                {pct(row.pick_rate, 1)}
              </span>
              <span role="cell" className="md:text-right md:text-ink-dim">
                <span className="md:sr-only">Ban </span>
                {pct(row.ban_rate, 1)}
              </span>
              <span role="cell" className="md:text-right">
                {compact(row.games)}
                <span className="md:sr-only"> games</span>
              </span>
              <span role="cell" className="md:text-right">
                <span className="md:sr-only">Gold @14 </span>
                <Gold row={row} />
              </span>
            </div>
            <span role="cell" className="tnum hidden text-right text-ink-dim md:block">
              {row.avg_kda.toFixed(2)}
            </span>
            <span role="cell" className="tnum hidden text-right text-ink-dim md:block">
              {row.avg_cs_per_min.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * The move since the close earlier patch, only where it is real: the two 95%
 * ranges no longer overlap, which 2 of 293 twenty-point moves did between
 * 16.17 and 16.18. An unmarked row is the ordinary case, not a gap.
 */
function Trend({ row, previousPatch }: { row: ChampionMetaRow; previousPatch: string | null }) {
  if (!row.win_rate_moved || row.previous_win_rate === null || !previousPatch) return null
  const points = (row.win_rate - row.previous_win_rate) * 100
  return (
    <span className={`tnum mt-1 block text-[11px] ${points >= 0 ? 'text-win' : 'text-loss'}`}>
      {points >= 0 ? '+' : ''}
      {points.toFixed(1)} since {previousPatch}
    </span>
  )
}
