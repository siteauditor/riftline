import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { PairEntry } from '../../lib/api'
import { compact, positionLabel } from '../../lib/format'
import { foldName } from '../../lib/searchParams'
import { EmptyState } from '../StateViews'
import WinRateRange from '../WinRateRange'
import { Chip, ChipGroup } from '@/components/ui/chips'

/** Which way a pair list reads: the worst pairings first, or the best. */
export type PairOrder = 'worst' | 'best'

// Rows shown before "Show all". The list itself is complete: at a cap of 15
// most opponents could not be looked up at all.
const SHOWN = 15

interface Props {
  title: string
  hint?: string
  rows: PairEntry[]
  order: PairOrder
  /** Text from `PairControls`; matching rows are all shown. */
  query: string
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
  /** Where a row's champion links, carrying the slice being read. */
  linkFor: (row: PairEntry) => string
}

/**
 * Both ways by the middle of the range the sample supports, which is the record
 * pulled toward 50% by about four games. Ordered by the bottom of the range,
 * Jinx's 4th "hardest" lane was Viktor at 3-3; by the top, Yunara at 10-9 was
 * 2nd, only because more games made its range the narrowest.
 */
const middle = (row: PairEntry) => (row.confidence_win_rate + row.confidence_high) / 2

function ordered(rows: PairEntry[], order: PairOrder): PairEntry[] {
  return [...rows].sort(
    (a, b) => (order === 'worst' ? middle(a) - middle(b) : middle(b) - middle(a)) || b.games - a.games,
  )
}

/**
 * Counters and synergies share a shape, so they share a table.
 *
 * The rate leads, with the range its sample supports drawn underneath, so the
 * order can be read in both directions: the bar sits low on the left of a
 * hard matchup and high on the right of an easy one.
 */
export default function PairTable({
  title,
  hint,
  rows,
  order,
  query,
  showPosition,
  showGold,
  linkFor,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  if (rows.length === 0) {
    return (
      <EmptyState
        title={`No ${title.toLowerCase()} yet`}
        body="No pairing in this slice clears the minimum sample. Lower 'min games', or ingest more matches."
      />
    )
  }

  const needle = foldName(query)
  const all = ordered(rows, order)
  const matching = needle ? all.filter((r) => foldName(r.champion.name).includes(needle)) : all
  const shown = needle || expanded ? matching : matching.slice(0, SHOWN)

  return (
    // `min-w-0`: this sits in a grid on the Counters tab, and a grid item's
    // automatic minimum is its content's, so the table's 380px floor widened
    // the page on a phone instead of scrolling inside the wrapper below.
    <section className="min-w-0">
      <div className="mb-2">
        <h3 className="display text-base font-600 text-ink">{title}</h3>
        {hint && <p className="mt-0.5 text-xs leading-relaxed text-ink-faint">{hint}</p>}
      </div>

      {matching.length === 0 ? (
        <p className="py-3 text-sm text-ink-faint">
          Nobody here matches &ldquo;{query.trim()}&rdquo;. They may have too few games in
          this slice; lower &lsquo;min games&rsquo; to include them.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[380px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-ink-faint">
                <th className="py-1.5 text-left font-500">Champion</th>
                <th
                  className="py-1.5 text-right font-500"
                  title="Ordered by the middle of the range the sample supports, which pulls a thin sample toward 50%"
                >
                  Win rate
                </th>
                {showGold && (
                  <th
                    className="py-1.5 pl-3 text-right font-500"
                    title="This champion's gold lead over the listed laner at 14 minutes, averaged over the games with a timeline"
                  >
                    Gold @14
                  </th>
                )}
                <th className="py-1.5 pl-3 text-right font-500">Games</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr
                  key={`${row.champion.id}-${row.position ?? ''}`}
                  className="lift border-b border-line-soft"
                >
                  <td className="py-2">
                    <Link to={linkFor(row)} className="group flex items-center gap-2">
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
                  <td className="py-2 text-right">
                    <WinRateRange
                      rate={row.win_rate}
                      low={row.confidence_win_rate}
                      high={row.confidence_high}
                      games={row.games}
                      size="sm"
                      rankedOn="middle"
                    />
                  </td>
                  {showGold && (
                    <td className="tnum py-2 pl-3 text-right">
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
                  <td className="tnum py-2 pl-3 text-right text-ink-faint">
                    {compact(row.games)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!needle && matching.length > SHOWN && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          className="mt-2 text-xs text-ink-dim underline decoration-line underline-offset-2 transition-colors hover:text-gold-bright"
        >
          {expanded ? `Show the first ${SHOWN}` : `Show all ${matching.length}`}
        </button>
      )}
    </section>
  )
}

/** One search box and one order toggle for the pair tables on a tab. */
export function PairControls({
  query,
  onQuery,
  order,
  onOrder,
  worstLabel,
  bestLabel,
  placeholder,
}: {
  query: string
  onQuery: (value: string) => void
  order: PairOrder
  onOrder: (order: PairOrder) => void
  worstLabel: string
  bestLabel: string
  placeholder: string
}) {
  const options: { value: PairOrder; label: string }[] = [
    { value: 'worst', label: worstLabel },
    { value: 'best', label: bestLabel },
  ]
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-3 text-sm">
      <label className="flex min-w-0 flex-1 items-center sm:max-w-xs">
        <span className="sr-only">{placeholder}</span>
        <input
          type="search"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          placeholder={placeholder}
          spellCheck={false}
          autoComplete="off"
          className="control w-full"
        />
      </label>
      <ChipGroup label="Order" className="gap-1">
        {options.map((o) => (
          <Chip key={o.value} size="sm" active={order === o.value} onClick={() => onOrder(o.value)}>
            {o.label}
          </Chip>
        ))}
      </ChipGroup>
    </div>
  )
}
