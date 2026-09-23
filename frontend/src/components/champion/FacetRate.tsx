import type { FacetEntry } from '../../lib/api'
import { compact, pct } from '../../lib/format'
import WinRateRange from '../WinRateRange'

/**
 * A facet's win rate with the range its sample supports: the rows are listed
 * by how often they were taken, and a rate over five games, coloured gold from
 * 55%, said more than its sample could.
 */
export default function FacetRate({ entry }: { entry: FacetEntry }) {
  return (
    <div className="ml-auto flex shrink-0 items-end gap-3 text-right">
      <p className="tnum pb-0.5 text-xs text-ink-faint">
        {compact(entry.games)} games
        <span className="block">{pct(entry.pick_rate)} of games</span>
      </p>
      <WinRateRange
        rate={entry.win_rate}
        low={entry.range_low}
        high={entry.range_high}
        games={entry.games}
        size="sm"
        description={`${pct(entry.win_rate, 1)} over ${entry.games} games, a range of ${pct(entry.range_low, 0)} to ${pct(entry.range_high, 0)}`}
      />
    </div>
  )
}
