import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
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
import { compact, pct, positionLabel, shortDate, tierColor, tierLabel } from '../lib/format'
import {
  foldName,
  SLICE_DEFAULTS,
  sliceFromParams,
  sliceLink,
  sliceParams,
  useSearchText,
  withParams,
} from '../lib/searchParams'
import { useChampionArt } from '../lib/useChampionArt'

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

// Below this many games with a timeline, an average gold lead is one or two
// stomps, so the cell shows a dash rather than a number.
const GOLD_FLOOR = 10

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

function goldAt14(row: ChampionMetaRow): number | null {
  return row.timeline_games >= GOLD_FLOOR ? row.avg_gold_diff_14 : null
}

// Champions without the figure sort last whichever way round: a missing gold
// lead is not a small one.
function sortValue(row: ChampionMetaRow, key: SortKey): number | null {
  return key === 'gold' ? goldAt14(row) : row[key]
}

export default function Tierlist() {
  // Everything that shapes the list lives in the URL. In component state it
  // was lost on the way back from a champion: pick Jungle, open Skarner, press
  // back, and the list was on All roles again (reproduced on the live site).
  const [params, setParams] = useSearchParams()
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
  const ranked = useMemo(() => {
    const rows = [...(meta.data?.rows ?? [])]
    rows.sort((a, b) => {
      const va = sortValue(a, sort)
      const vb = sortValue(b, sort)
      if (va === null && vb === null) return b.confidence_win_rate - a.confidence_win_rate
      if (va === null) return 1
      if (vb === null) return -1
      return vb - va
    })
    return rows.map((row, i) => ({ row, place: i + 1 }))
  }, [meta.data, sort])

  const query = foldName(search)
  const shown = query
    ? ranked.filter(({ row }) => foldName(row.champion.name).includes(query))
    : ranked
  const queueName = slice.queueId === 440 ? 'ranked flex' : 'ranked solo'
  const linkFor = (row: ChampionMetaRow) =>
    `/champions/${row.champion.slug ?? row.champion.id}${sliceLink({ ...slice, position: row.position })}`
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
            title="No matches ingested yet"
            body="Tier lists are built from a corpus of matches. Run the crawler to collect some: python -m scripts.ingest crawl --target 500, then python -m scripts.ingest aggregate."
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

          {rows.length > 0 && rows.every((r) => r.tier === null) && (
            <p className="mt-4 border-l-2 border-gold/50 py-1 pl-3 text-sm text-ink-dim">
              Every role has too few champions with enough games in this slice to rank
              them against each other, so the tier column is blank. The numbers below are
              still real. Lower &ldquo;min games&rdquo; to widen the list, or ingest more
              matches.
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
                  <Table
                    rows={shown}
                    sort={sort}
                    onSort={setSort}
                    showRole={!position}
                    linkFor={linkFor}
                  />
                  <Cards rows={shown} showRole={!position} linkFor={linkFor} />
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
 * How the games behind this slice were ranked.
 *
 * Measured, not assumed: each lobby's median rank. The crawler starts from the
 * top of the ladder, so on 16.18 95% of the games were Master+ lobbies, and a
 * Gold player reading this list should know that. Riot keeps no historical
 * rank, so the measurement is where those players stood on the day it was
 * taken, which the line says.
 */
function LobbyRanks({ lobby }: { lobby: NonNullable<MetaResponse['lobby_ranks']> }) {
  if (lobby.measured === 0) return null
  const top = lobby.buckets[0]
  const label = (tier: string) => (tier === 'MASTER+' ? 'Master+' : tierLabel(tier))
  const colour = (tier: string) => tierColor(tier === 'MASTER+' ? 'MASTER' : tier)
  const measuredOn = lobby.as_of ? shortDate(lobby.as_of) : null
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-dim">
      <span className="flex h-1.5 w-32 overflow-hidden rounded-full bg-raised" aria-hidden>
        {lobby.buckets.map((b) => (
          <span
            key={b.tier}
            style={{ width: `${(b.games / lobby.measured) * 100}%`, background: colour(b.tier) }}
          />
        ))}
      </span>
      <span title={lobby.buckets.map((b) => `${label(b.tier)}: ${b.games}`).join(', ')}>
        <span className="tnum text-ink">{pct(top.games / lobby.measured)}</span> of these
        games were {label(top.tier)} lobbies
        <span className="text-ink-faint">
          {' '}
          ({lobby.measured.toLocaleString('en-US')} of {lobby.total.toLocaleString('en-US')} measured)
        </span>
      </span>
      <span className="text-ink-faint">
        Median rank of each lobby
        {measuredOn ? `, measured ${measuredOn}` : ''}, not when the games were played.
      </span>
    </div>
  )
}

function TierBadge({ tier }: { tier: string | null }) {
  if (!tier) {
    return (
      <span
        className="text-ink-faint"
        title="Too few champions in this role to rank them against each other"
      >
        –
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
      title={`Tier ${tier} within its role on this patch`}
    >
      {tier}
    </span>
  )
}

function Gold({ row }: { row: ChampionMetaRow }) {
  const gold = goldAt14(row)
  if (gold === null) {
    return (
      <span
        className="text-ink-faint"
        title={`${row.timeline_games} games with a timeline, too few to average`}
      >
        –
      </span>
    )
  }
  return (
    <span
      className={gold >= 0 ? 'text-win' : 'text-loss'}
      title={`Average gold lead at 14 minutes over ${row.timeline_games} games with a timeline`}
    >
      {gold >= 0 ? '+' : ''}
      {Math.round(gold).toLocaleString('en-US')}
    </span>
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
  { key: 'pick_rate', label: 'Pick', hint: 'Share of games this champion was picked' },
  { key: 'ban_rate', label: 'Ban', hint: 'Share of games this champion was banned' },
  { key: 'games', label: 'Games', hint: 'Sample size' },
  { key: 'gold', label: 'Gold @14', hint: 'Average gold lead at 14 minutes' },
  { key: 'avg_kda', label: 'KDA', hint: 'Kills and assists per death' },
  { key: 'avg_cs_per_min', label: 'CS/m', hint: 'Minions and monsters per minute' },
]

function Table({
  rows,
  sort,
  onSort,
  showRole,
  linkFor,
}: {
  rows: { row: ChampionMetaRow; place: number }[]
  sort: SortKey
  onSort: (key: SortKey) => void
  showRole: boolean
  linkFor: (row: ChampionMetaRow) => string
}) {
  return (
    <div className="mt-3 hidden overflow-x-auto md:block">
      <table className="w-full min-w-[720px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line text-xs text-ink-faint">
            <th className="w-9 py-2.5 text-left font-500">#</th>
            <th className="w-12 py-2.5 text-left font-500">Tier</th>
            <th className="py-2.5 text-left font-500">Champion</th>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                aria-sort={sort === c.key ? 'descending' : 'none'}
                className="py-2.5 text-right font-500"
              >
                <button
                  onClick={() => onSort(c.key)}
                  title={c.hint}
                  className={`border-b-2 pb-0.5 transition-colors ${
                    sort === c.key
                      ? 'border-gold text-gold-bright'
                      : 'border-transparent hover:text-ink'
                  }`}
                >
                  {c.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ row, place }) => (
            <tr
              key={`${row.champion.id}-${row.position}`}
              className="lift border-b border-line-soft"
            >
              <td className="tnum py-2.5 text-xs text-ink-faint">{place}</td>
              <td className="py-2.5">
                <TierBadge tier={row.tier} />
              </td>
              <td className="py-2.5">
                <Link to={linkFor(row)} viewTransition className="group block">
                  <ChampionCell row={row} showRole={showRole} />
                </Link>
              </td>
              <td className="py-2.5 text-right">
                <WinRateRange
                  rate={row.win_rate}
                  low={row.confidence_win_rate}
                  high={row.confidence_high}
                  games={row.games}
                />
              </td>
              <td className="tnum py-2.5 text-right text-ink-dim">{pct(row.pick_rate, 1)}</td>
              <td className="tnum py-2.5 text-right text-ink-dim">{pct(row.ban_rate, 1)}</td>
              <td className="tnum py-2.5 text-right text-ink-faint">{compact(row.games)}</td>
              <td className="tnum py-2.5 text-right">
                <Gold row={row} />
              </td>
              <td className="tnum py-2.5 text-right text-ink-dim">{row.avg_kda.toFixed(2)}</td>
              <td className="tnum py-2.5 text-right text-ink-dim">
                {row.avg_cs_per_min.toFixed(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The phone layout: one card per champion.
 *
 * The table needed 720px, so at 390px its win rate column sat off-screen and a
 * reader saw names and tiers but no number without scrolling sideways. A card
 * puts the tier, the champion and the win rate range in one row, with the rest
 * on a line beneath.
 */
function Cards({
  rows,
  showRole,
  linkFor,
}: {
  rows: { row: ChampionMetaRow; place: number }[]
  showRole: boolean
  linkFor: (row: ChampionMetaRow) => string
}) {
  return (
    <ul className="mt-3 md:hidden">
      {rows.map(({ row, place }) => (
        <li key={`${row.champion.id}-${row.position}`} className="border-b border-line-soft">
          <Link to={linkFor(row)} viewTransition className="group block py-3">
            <span className="grid grid-cols-[1.5rem_1.75rem_minmax(0,1fr)_auto] items-center gap-x-2.5">
              <span className="tnum text-xs text-ink-faint">{place}</span>
              <TierBadge tier={row.tier} />
              <ChampionCell row={row} showRole={showRole} />
              <WinRateRange
                rate={row.win_rate}
                low={row.confidence_win_rate}
                high={row.confidence_high}
                games={row.games}
              />
            </span>
            <span className="tnum mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 pl-[4.5rem] text-[11px] text-ink-faint">
              <span>{compact(row.games)} games</span>
              <span>Pick {pct(row.pick_rate, 1)}</span>
              <span>Ban {pct(row.ban_rate, 1)}</span>
              <span>
                Gold @14 <Gold row={row} />
              </span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}
