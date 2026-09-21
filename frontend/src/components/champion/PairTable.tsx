import { Link } from 'react-router-dom'

import type { PairEntry } from '../../lib/api'
import { EmptyState } from '../StateViews'
import { compact, pct, positionLabel } from '../../lib/format'

interface Props {
  title: string
  hint?: string
  rows: PairEntry[]
  /** Synergies carry the ally's lane; matchups do not. */
  showPosition?: boolean
  /**
   * Gold difference at 14 minutes.
   *
   * Only meaningful for lane matchups. On the team and synergy tables the same
   * number is this champion's gap against *their own laner* in games where the
   * listed champion happened to be present, which is not what a column headed
   * "Gold @14" next to a name reads as, so those tables leave it off.
   */
  showGold?: boolean
}

/**
 * Counters and synergies share a shape, so they share a table.
 *
 * Two columns of win rate are shown on purpose. The raw rate is what people
 * expect to see; the adjusted one is what the row is actually ordered by, and
 * on a thin sample the gap between them is the honest story.
 */
export default function PairTable({ title, hint, rows, showPosition, showGold }: Props) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title={`No ${title.toLowerCase()} yet`}
        body="No pairing in this slice clears the minimum sample. Lower 'min games', or ingest more matches."
      />
    )
  }

  return (
    <section>
      <div className="mb-2">
        <h3 className="display text-base font-600 text-ink">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-relaxed text-ink-faint">{hint}</p>}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[380px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="py-1.5 text-left font-500">Champion</th>
              <th className="py-1.5 text-right font-500" title="Ordered by this">
                Adjusted
              </th>
              <th className="py-1.5 text-right font-500">Win rate</th>
              {showGold && (
                <th
                  className="py-1.5 text-right font-500"
                  title="This champion's gold lead over the listed laner at 14 minutes, averaged over the games with a timeline"
                >
                  Gold @14
                </th>
              )}
              <th className="py-1.5 text-right font-500">Games</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.champion.id}-${row.position ?? ''}`}
                className="lift border-b border-line-soft"
              >
                <td className="py-1.5">
                  <Link
                    to={`/champions/${row.champion.id}`}
                    className="group flex items-center gap-2"
                  >
                    {row.champion.icon_url && (
                      <img
                        src={row.champion.icon_url}
                        alt=""
                        className="size-7 rounded-sm ring-1 ring-line transition-[box-shadow] group-hover:ring-gold"
                        loading="lazy"
                      />
                    )}
                    <span className="display truncate text-[15px] font-600 text-ink transition-colors group-hover:text-gold-bright">
                      {row.champion.name}
                    </span>
                    {showPosition && row.position && (
                      <span className="text-xs text-ink-faint">
                        {positionLabel(row.position)}
                      </span>
                    )}
                  </Link>
                </td>
                <td className="tnum py-1.5 text-right font-600 text-ink">
                  {pct(row.confidence_win_rate, 1)}
                </td>
                <td className="tnum py-1.5 text-right text-ink-dim">
                  {pct(row.win_rate, 1)}
                </td>
                {showGold && (
                  <td className="tnum py-1.5 text-right">
                    {row.avg_gold_diff_14 === null ? (
                      <span className="text-line" title="No timeline for this matchup yet">
                        &ndash;
                      </span>
                    ) : (
                      <span
                        style={{
                          color:
                            row.avg_gold_diff_14 >= 0
                              ? 'var(--color-win)'
                              : 'var(--color-loss)',
                        }}
                      >
                        {row.avg_gold_diff_14 >= 0 ? '+' : ''}
                        {Math.round(row.avg_gold_diff_14)}
                      </span>
                    )}
                  </td>
                )}
                <td className="tnum py-1.5 text-right text-ink-faint">
                  {compact(row.games)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
