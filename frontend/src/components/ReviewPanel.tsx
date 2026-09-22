import type { LaneRecord, ReviewMetric, RoleReview } from '../lib/api'
import { pct, positionLabel } from '../lib/format'
import { LANE_TEXT, laneColor } from './story/lanes'

/**
 * Deaths and takedowns, and lanes, over the stored games with a timeline.
 *
 * The review's four rates are placed against the same role, a percentile per
 * game averaged the way the score is, so "better than 64% of mid laners" means
 * the same thing on every profile. Below ten reviewed games in a role the rates
 * are withheld and the count shown, because three games place nobody.
 */
export default function ReviewPanel({
  review,
  lanes,
}: {
  review: RoleReview[] | undefined
  lanes: LaneRecord[] | undefined
}) {
  const main = review?.[0]
  const lane = lanes?.[0]
  if (!main && !lane) return null

  return (
    <section className="frame">
      <header className="border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">Deaths and takedowns</h2>
      </header>
      <div className="space-y-4 px-4 py-3 text-xs">
        {main && (
          <div>
            <p className="mb-2 text-ink-faint">
              As {positionLabel(main.position).toLowerCase()}, over {main.games.toLocaleString('en-US')}{' '}
              {main.games === 1 ? 'game' : 'games'} with a timeline
            </p>
            {main.withheld ? (
              <p className="leading-relaxed text-ink-dim">
                {main.games} of the {main.min_games} games the review needs in a role before it
                places anyone.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {main.metrics.map((m) => (
                  <Metric key={m.metric} metric={m} position={main.position} />
                ))}
              </ul>
            )}
            {main.contests > 0 && (
              <p className="mt-2.5 text-ink-dim">
                Objective fights won:{' '}
                <span className="tnum text-ink">
                  {main.contests_won} of {main.contests}
                </span>
              </p>
            )}
          </div>
        )}

        {lane && <Lanes record={lane} />}
      </div>
    </section>
  )
}

function Metric({ metric, position }: { metric: ReviewMetric; position: string }) {
  // Shares read as percentages; win chance per 30 minutes as points.
  const share = metric.metric.endsWith('untraded') || metric.metric.endsWith('converted')
  const value = share ? pct(metric.value) : `${(metric.value * 100).toFixed(1)} pts`
  return (
    <li title={metric.measures}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-ink-dim">{metric.label}</span>
        <span className="tnum text-ink">{value}</span>
      </div>
      {metric.better_than !== null ? (
        <div className="mt-1 flex items-center gap-2">
          <span className="h-1 flex-1 overflow-hidden rounded-full bg-raised">
            <span
              className="block h-full"
              style={{ width: `${metric.better_than * 100}%`, background: 'var(--accent)' }}
            />
          </span>
          <span className="tnum shrink-0 text-[11px] text-ink-faint">
            better than {pct(metric.better_than)} of {positionLabel(position).toLowerCase()} games
          </span>
        </div>
      ) : (
        <p className="mt-0.5 text-[11px] text-ink-faint">Too few games in this role to place it.</p>
      )}
    </li>
  )
}

function Lanes({ record }: { record: LaneRecord }) {
  const parts = (['won_big', 'won', 'even', 'lost', 'lost_big'] as const).filter((k) => record[k] > 0)
  const won = record.won + record.won_big
  const lost = record.lost + record.lost_big
  return (
    <div>
      <p className="mb-1.5 text-ink-faint">
        Lanes as {positionLabel(record.position).toLowerCase()}, at 14 minutes
      </p>
      <div className="flex h-2 overflow-hidden rounded-full bg-raised" aria-hidden>
        {parts.map((k) => (
          <span
            key={k}
            title={`${LANE_TEXT[k]}: ${record[k]}`}
            style={{
              width: `${(record[k] / record.games) * 100}%`,
              background: laneColor(k),
              opacity: k === 'won' || k === 'lost' ? 0.6 : 1,
            }}
          />
        ))}
      </div>
      <p className="tnum mt-1.5 text-ink-dim">
        {won} won{record.won_big ? ` (${record.won_big} big)` : ''}, {record.even} even, {lost} lost
        {record.lost_big ? ` (${record.lost_big} big)` : ''}, of {record.games}
      </p>
    </div>
  )
}
