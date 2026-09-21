import type { ChampionDetail } from '../../lib/api'
import { EmptyState } from '../StateViews'
import { compact, pct } from '../../lib/format'

interface Props {
  laning: ChampionDetail['laning']
  championName: string
}

/**
 * How the laning phase goes, measured at minute 14.
 *
 * It comes from match timelines, which are fetched separately from matches, so
 * a champion can have hundreds of games and no laning data at all. The header
 * states the sample outright rather than letting an average imply the full
 * game count. Skill order used to share this tab and now lives under
 * Abilities, beside the abilities it is about.
 */
export default function LaningPanel({ laning, championName }: Props) {
  if (laning.games === 0 || laning.avg_score === null) {
    return (
      <EmptyState
        title="No timeline data yet"
        body="Laning figures come from match timelines, which are fetched separately from matches. None of this slice's games has one yet."
      />
    )
  }

  const score = laning.avg_score
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
        <h3 className="display text-base font-600 text-ink">Laning phase</h3>
        <p className="text-xs text-ink-faint">
          Measured at 14 minutes, over {compact(laning.games)} game
          {laning.games === 1 ? '' : 's'} with a timeline.
        </p>
      </div>

      <div className="frame px-4 py-3.5">
        {/* The share bar is the number: 52:48 is legible at a glance in a
            way "0.52" is not. */}
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-display font-700 text-ink">{championName}</span>
          <span className="tnum font-display text-lg font-800 text-gold-bright">
            {Math.round(score * 100)}
            <span className="mx-1 text-ink-faint">:</span>
            <span className="text-ink-dim">{100 - Math.round(score * 100)}</span>
          </span>
          <span className="text-ink-faint">opponent</span>
        </div>

        <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-raised">
          <div
            className="bg-win"
            style={{ width: `${score * 100}%` }}
            aria-label={`${championName} takes ${pct(score)} of the lane`}
          />
          <div className="flex-1 bg-loss/60" aria-hidden />
        </div>

        {/* Stacked label over value, matching the average cells above the
            tabs: at this width a justified pair drifts too far apart to
            read as one thing. */}
        <dl className="mt-3.5 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Diff label="Gold at 14" value={laning.avg_gold_diff} />
          <Diff label="CS at 14" value={laning.avg_cs_diff} digits={1} />
          <div>
            <dt className="text-xs text-ink-faint">Sample</dt>
            <dd className="tnum mt-0.5 text-sm font-600 text-ink">
              {compact(laning.games)} games
            </dd>
          </div>
        </dl>
      </div>
    </section>
  )
}

function Diff({
  label,
  value,
  digits = 0,
}: {
  label: string
  value: number | null
  digits?: number
}) {
  if (value === null) return null
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd
        className="tnum mt-0.5 text-sm font-600"
        style={{ color: value >= 0 ? 'var(--color-win)' : 'var(--color-loss)' }}
      >
        {value >= 0 ? '+' : ''}
        {value.toFixed(digits)}
      </dd>
    </div>
  )
}
