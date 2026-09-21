import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'

import Crest from './Crest'
import { api, type RankHistory, type RankInfo } from '../lib/api'
import { pct, tierColor, tierLabel } from '../lib/format'

interface PlayerKey {
  platform: string
  name: string
  tag: string
}

/**
 * A ranked queue at a glance.
 *
 * This is the one place a rank is the subject rather than a label, so it gets
 * Riot's full emblem at the size it was drawn for, with the tier's colour on
 * the type and the rule. The win/loss bar is the honest version of a win rate:
 * it shows sample size and split in the same object.
 */
export default function RankCard({
  rank,
  player,
  compact = false,
}: {
  rank: RankInfo
  player?: PlayerKey
  /** One line, for the top of a phone screen where the games have to follow fast. */
  compact?: boolean
}) {
  const color = tierColor(rank.tier)
  const ranked = Boolean(rank.tier)

  if (compact) {
    return (
      <div
        className="accent-edge flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-r-sm border-y border-r border-line bg-panel px-3 py-2 text-xs"
        style={{ '--accent': color } as CSSProperties}
      >
        <span className="text-ink-dim">{rank.queue_label}</span>
        {ranked ? (
          <span className="tnum flex items-baseline gap-2.5">
            <span className="display text-sm font-600" style={{ color }}>
              {tierLabel(rank.tier, rank.division)}
            </span>
            <span className="text-ink">{rank.league_points.toLocaleString()} LP</span>
            <span>
              <span className="text-win">{rank.wins}W</span>{' '}
              <span className="text-loss">{rank.losses}L</span>
            </span>
            <span className="text-ink-dim">{pct(rank.win_rate)}</span>
          </span>
        ) : (
          <span className="text-ink-faint">Unranked this season</span>
        )}
      </div>
    )
  }

  return (
    // The rule carries this queue's own tier, which is not always the one the
    // page header shows: plenty of players are two tiers apart in solo and flex.
    <section
      className="accent-edge rounded-r-sm border-y border-r border-line bg-panel"
      style={{ '--accent': color } as CSSProperties}
    >
      <header className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">{rank.queue_label}</h2>
        {rank.hot_streak && (
          <span className="rounded-sm bg-gold/15 px-1.5 py-0.5 text-[11px] font-600 text-gold-bright">
            Hot streak
          </span>
        )}
      </header>

      <div className="px-4 py-3.5">
        {ranked ? (
          <>
            <div className="flex items-center gap-3">
              {/* The emblem is one of the two places a rank is the subject
                  rather than a label, so it gets the full art and its glow. */}
              <Crest tier={rank.tier} division={rank.division} size="card" />
              <div className="min-w-0">
                <p
                  className="display text-[26px] font-700 uppercase leading-none tracking-tight"
                  style={{ color }}
                >
                  {tierLabel(rank.tier, rank.division)}
                </p>
                <p className="mt-1.5 text-sm text-ink-dim">
                  <span className="tnum font-600 text-ink">
                    {rank.league_points.toLocaleString()}
                  </span>{' '}
                  LP
                </p>
              </div>
            </div>

            <div className="mt-3.5">
              <div className="flex h-1.5 overflow-hidden rounded-full bg-raised">
                <div
                  className="bg-win"
                  style={{ width: `${rank.win_rate * 100}%` }}
                  aria-hidden
                />
                <div className="flex-1 bg-loss/70" aria-hidden />
              </div>
              <div className="mt-1.5 flex justify-between text-xs text-ink-dim">
                <span className="tnum">
                  <span className="text-win">{rank.wins}W</span>
                  <span className="mx-1 text-ink-faint">/</span>
                  <span className="text-loss">{rank.losses}L</span>
                </span>
                <span className="tnum">{pct(rank.win_rate)}</span>
              </div>
            </div>

            {player && <LpHistory player={player} queue={rank.queue} />}
          </>
        ) : (
          <p className="text-sm text-ink-faint">Unranked this season</p>
        )}
      </div>
    </section>
  )
}

const DAY_MS = 86_400_000

const dateLabel = (ms: number) =>
  new Date(ms).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

/**
 * The rank over time, from readings Riftline took itself.
 *
 * Riot keeps no rank history, so the line starts on the day we first read this
 * player and has a point only where the rank moved. Until there are two points
 * a day apart there is no line worth drawing, and the card says when tracking
 * began instead of drawing a flat stub that would read as "no change".
 */
function LpHistory({ player, queue }: { player: PlayerKey; queue: string }) {
  const { data } = useQuery({
    queryKey: ['rank-history', player.platform, player.name, player.tag, queue],
    queryFn: () => api.rankHistory(player.platform, player.name, player.tag, queue),
    staleTime: 5 * 60_000,
    retry: false,
  })
  if (!data) return null

  const points = data.points
  const span = points.length > 1 ? points[points.length - 1].at - points[0].at : 0
  if (points.length < 2 || span < DAY_MS) {
    return (
      <p className="mt-3 text-[11px] text-ink-faint">
        {data.tracking_since
          ? `LP tracked since ${dateLabel(data.tracking_since)}. The graph starts once the rank moves.`
          : 'LP tracking starts with the next update.'}
      </p>
    )
  }
  return <LpLine history={data} />
}

function LpLine({ history }: { history: RankHistory }) {
  const points = history.points
  const width = 240
  const height = 48
  const pad = 4
  const first = points[0].at
  const last = points[points.length - 1].at
  const low = Math.min(...points.map((p) => p.numeric_rank))
  const high = Math.max(...points.map((p) => p.numeric_rank))
  // A flat line still needs a band to sit in, or it divides by zero.
  const range = Math.max(high - low, 40)
  const x = (at: number) => pad + ((at - first) / (last - first)) * (width - pad * 2)
  const y = (rank: number) =>
    height - pad - ((rank - low) / range) * (height - pad * 2)
  const line = points.map((p) => `${x(p.at).toFixed(1)},${y(p.numeric_rank).toFixed(1)}`).join(' ')

  return (
    <figure className="mt-3">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-auto w-full"
        role="img"
        aria-label={`Rank from ${dateLabel(first)} to ${dateLabel(last)}`}
      >
        <polyline
          points={line}
          fill="none"
          stroke="var(--accent)"
          strokeWidth="1.5"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
        {points.map((p) => (
          <circle key={p.at} cx={x(p.at)} cy={y(p.numeric_rank)} r="2" fill="var(--accent)">
            <title>
              {`${dateLabel(p.at)}: ${tierLabel(p.tier, p.division)}, ${p.league_points.toLocaleString()} LP`}
            </title>
          </circle>
        ))}
      </svg>
      <figcaption className="mt-0.5 flex justify-between text-[10px] text-ink-faint">
        <span>{dateLabel(first)}</span>
        <span>{dateLabel(last)}</span>
      </figcaption>
    </figure>
  )
}
