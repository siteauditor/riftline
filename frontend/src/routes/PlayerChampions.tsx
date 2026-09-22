import { useMemo } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import PositionIcon from '../components/PositionIcon'
import ProfileTabs from '../components/ProfileTabs'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { api, type ChampionPlayed } from '../lib/api'
import { heads } from '../lib/seo'
import {
  kdaColor,
  pct,
  positionLabel,
  scoreColor,
  timeAgo,
  winRateColor,
} from '../lib/format'
import { intParam, withParams } from '../lib/searchParams'
import { useChampionArt } from '../lib/useChampionArt'

const QUEUES = [
  { id: null, label: 'All' },
  { id: 420, label: 'Solo/Duo' },
  { id: 440, label: 'Flex' },
  { id: 450, label: 'ARAM' },
]

// The analytics endpoint's ceiling. A champion table is where a long history
// pays off, so it asks for all of it rather than the Overview's 300.
const LIMIT = 1000

type SortKey = 'games' | 'win_rate' | 'kda' | 'cs' | 'damage' | 'score' | 'gold'

const COLUMNS: { key: SortKey; label: string; title: string }[] = [
  { key: 'games', label: 'Games', title: 'Stored games on this champion' },
  { key: 'win_rate', label: 'Win rate', title: 'Share of those games won' },
  { key: 'kda', label: 'KDA', title: 'Average kills, deaths and assists' },
  { key: 'cs', label: 'CS/min', title: 'Minions and monsters per minute' },
  { key: 'damage', label: 'Dmg/min', title: 'Damage to champions per minute' },
  { key: 'score', label: 'Score', title: 'Average Riftline score, over the scored games' },
  {
    key: 'gold',
    label: 'Gold @14',
    title: 'Average gold lead at 14 minutes, over the games with a timeline',
  },
]

// Champions without a figure for the column sort last whichever way round,
// because a missing score is not a low one.
function value(row: ChampionPlayed, key: SortKey): number | null {
  switch (key) {
    case 'games':
      return row.games
    case 'win_rate':
      return row.win_rate
    case 'kda':
      return row.kda
    case 'cs':
      return row.cs_per_min
    case 'damage':
      return row.damage_per_min
    case 'score':
      return row.avg_score
    case 'gold':
      return row.avg_gold_diff_14
  }
}

/**
 * Every champion this player has in storage, as one sortable table.
 *
 * The Overview's "most played" stops at five; this is the rest. Each average
 * carries its own count, because scores and timelines do not cover every game:
 * a champion with two scored games of nine shows its score as two games deep.
 */
export default function PlayerChampions() {
  const { platform = '', name = '', tag = '' } = useParams()
  // In the URL, so the table comes back as it was left after opening a
  // champion or a filtered history.
  const [search, setSearch] = useSearchParams()
  const queue = intParam(search, 'queue', 0) || null
  const sort: SortKey = COLUMNS.find((c) => c.key === search.get('sort'))?.key ?? 'games'
  const descending = search.get('dir') !== 'asc'
  const setView = (patch: { queue?: number | null; sort?: SortKey; dir?: 'asc' | 'desc' }) =>
    setSearch((prev) => withParams(prev, patch, { sort: 'games', dir: 'desc' }), { replace: true })

  const query = useQuery({
    queryKey: ['analytics', platform, name, tag, { queue, limit: LIMIT }],
    queryFn: () => api.analytics(platform, name, tag, { queue, limit: LIMIT }),
    retry: false,
  })

  const rows = useMemo(() => {
    const list = [...(query.data?.champions ?? [])]
    list.sort((a, b) => {
      const va = value(a, sort)
      const vb = value(b, sort)
      if (va === null && vb === null) return b.games - a.games
      if (va === null) return 1
      if (vb === null) return -1
      return descending ? vb - va : va - vb
    })
    return list
  }, [query.data, sort, descending])

  function sortBy(key: SortKey) {
    if (key === sort) setView({ dir: descending ? 'asc' : 'desc' })
    else setView({ sort: key, dir: 'desc' })
  }

  const base = `/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`
  const heroArt = useChampionArt(query.data?.champions[0]?.champion.id)
  const data = query.data

  return (
    <div>
      <Head {...heads.profileTab(`${name}#${tag}`, platform, 'champions')} />
      <ArtHeader art={heroArt}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-0">
            <p className="eyebrow">Champions played</p>
            <h1 className="display mt-1 text-[clamp(1.9rem,4.5vw,2.9rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
              {name}
              <span className="ml-2 text-[0.5em] font-600 text-ink-faint">#{tag}</span>
            </h1>
          </div>
          <ProfileTabs platform={platform} name={name} tag={tag} />
        </div>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">

      <div className="mt-5 flex items-center gap-1 text-sm">
        {QUEUES.map((q) => (
          <button
            key={q.label}
            type="button"
            onClick={() => setView({ queue: q.id })}
            aria-pressed={queue === q.id}
            className={`border-b-2 px-3 pb-1.5 pt-1 font-display font-600 transition-colors ${
              queue === q.id
                ? 'border-gold text-gold-bright'
                : 'border-transparent text-ink-dim hover:text-ink'
            }`}
          >
            {q.label}
          </button>
        ))}
      </div>

      {query.isLoading && (
        <div className="py-10">
          <Spinner label="Reading stored games" />
        </div>
      )}

      {query.isError && (
        <div className="py-6">
          <ErrorView
            error={query.error}
            context={`${name}#${tag}`}
            onRetry={() => query.refetch()}
          />
        </div>
      )}

      {data && rows.length === 0 && (
        <div className="py-6">
          <EmptyState
            title="No stored games here"
            body="Open the Overview to fetch recent games, or try another queue."
          />
        </div>
      )}

      {data && rows.length > 0 && (
        <>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-ink-faint">
                  <th className="py-2 pr-3 font-500">Champion</th>
                  {COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className="py-2 pl-3 text-right font-500"
                      aria-sort={
                        sort === c.key ? (descending ? 'descending' : 'ascending') : 'none'
                      }
                    >
                      <button
                        type="button"
                        onClick={() => sortBy(c.key)}
                        title={c.title}
                        className={`transition-colors hover:text-ink ${
                          sort === c.key ? 'text-gold-bright' : ''
                        }`}
                      >
                        {c.label}
                        {sort === c.key && (
                          <span aria-hidden className="ml-1">
                            {descending ? '↓' : '↑'}
                          </span>
                        )}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <ChampionRow
                    key={row.champion.id}
                    row={row}
                    historyHref={`${base}?${withParams(new URLSearchParams(), {
                      champion: row.champion.id,
                      queue,
                    }).toString()}`}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">
            From {data.games_analysed.toLocaleString('en-US')} stored games, not the whole
            season. Scores and gold at 14 cover only the games that were scored or have a
            timeline, and each shows how many. The{' '}
            <Link to={base} className="underline decoration-line underline-offset-2 hover:text-ink">
              Overview
            </Link>{' '}
            fetches more as you load match history.
          </p>
        </>
      )}
    </div>
    </div>
  )
}

function ChampionRow({ row, historyHref }: { row: ChampionPlayed; historyHref: string }) {
  const losses = row.games - row.wins
  return (
    <tr className="border-b border-line-soft">
      <td className="py-2 pr-3">
        <span className="flex items-center gap-2.5">
          {row.champion.icon_url ? (
            <img src={row.champion.icon_url} alt="" className="size-8 shrink-0 rounded-sm" />
          ) : (
            <span aria-hidden className="size-8 shrink-0 rounded-sm bg-raised" />
          )}
          <span className="min-w-0">
            <Link
              to={`/champions/${row.champion.slug ?? row.champion.id}${row.main_position ? `?position=${row.main_position}` : ''}`}
              className="display block truncate text-[15px] font-600 text-ink hover:text-gold-bright"
            >
              {row.champion.name}
            </Link>
            <span className="flex items-center gap-1 text-[11px] text-ink-faint">
              {row.main_position && (
                <>
                  <PositionIcon position={row.main_position} className="size-3" />
                  {positionLabel(row.main_position)}
                </>
              )}
              {row.last_played && <span className="ml-1">{timeAgo(row.last_played)}</span>}
            </span>
          </span>
        </span>
      </td>
      <td className="tnum py-2 pl-3 text-right">
        <Link
          to={historyHref}
          title={`These ${row.games} games in the match history`}
          className="text-ink underline decoration-line underline-offset-2 transition-colors hover:text-gold-bright hover:decoration-gold"
        >
          {row.games}
        </Link>
        <span className="block text-[11px] text-ink-faint">
          {row.wins}W {losses}L
        </span>
      </td>
      <td
        className="tnum py-2 pl-3 text-right font-600"
        style={{ color: winRateColor(row.win_rate, 0.6) }}
      >
        {pct(row.win_rate)}
      </td>
      <td className="tnum py-2 pl-3 text-right">
        <span
          className="font-600"
          style={{ color: kdaColor(row.kda, row.avg_deaths) }}
        >
          {row.kda.toFixed(2)}
        </span>
        <span className="block text-[11px] text-ink-faint">
          {row.avg_kills.toFixed(1)} / {row.avg_deaths.toFixed(1)} / {row.avg_assists.toFixed(1)}
        </span>
      </td>
      <td className="tnum py-2 pl-3 text-right text-ink">{row.cs_per_min.toFixed(1)}</td>
      <td className="tnum py-2 pl-3 text-right text-ink">
        {Math.round(row.damage_per_min).toLocaleString('en-US')}
      </td>
      <td className="tnum py-2 pl-3 text-right">
        {row.avg_score !== null ? (
          <>
            <span className="display text-base font-700" style={{ color: scoreColor(row.avg_score) }}>
              {row.avg_score.toFixed(1)}
            </span>
            <span className="block text-[11px] text-ink-faint">{row.scored_games} scored</span>
          </>
        ) : (
          <span className="text-ink-faint" title="No scored games on this champion">
            -
          </span>
        )}
      </td>
      <td className="tnum py-2 pl-3 text-right">
        {row.avg_gold_diff_14 !== null ? (
          <>
            <span className={row.avg_gold_diff_14 >= 0 ? 'text-win' : 'text-loss'}>
              {row.avg_gold_diff_14 >= 0 ? '+' : ''}
              {Math.round(row.avg_gold_diff_14).toLocaleString('en-US')}
            </span>
            <span className="block text-[11px] text-ink-faint">
              {row.timeline_games} game{row.timeline_games === 1 ? '' : 's'}
            </span>
          </>
        ) : (
          <span className="text-ink-faint" title="No games with a timeline on this champion">
            -
          </span>
        )}
      </td>
    </tr>
  )
}
