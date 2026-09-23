import { useState } from 'react'
import { Link } from 'react-router-dom'

import type { PairEntry } from '../../lib/api'
import { pct, positionLabel } from '../../lib/format'
import { foldName } from '../../lib/searchParams'
import Hint from '../Hint'
import { EmptyState } from '../StateViews'
import { Chip, ChipGroup } from '@/components/ui/chips'

/** Which way a pair list reads: the worst pairings first, or the best. */
export type PairOrder = 'worst' | 'best'

// Rows shown before "Show all". The list itself is complete: at a cap of 15
// most opponents could not be looked up at all.
const SHOWN = 15

const CALL_WORD: Record<PairEntry['call'], string> = {
  favoured: 'favoured',
  unfavoured: 'unfavoured',
  level: 'not called',
}

/** A gap from the champion's usual rate, in win-rate points. */
const points = (lift: number) => `${lift >= 0 ? '+' : ''}${(lift * 100).toFixed(1)}`

interface Props {
  title: string
  hint?: string
  rows: PairEntry[]
  order: PairOrder
  /** Text from `PairControls`; matching rows are all shown. */
  query: string
  /** The champion the records are about, for the header's explanation. */
  championName: string
  /** The prior these records are read with, in games. */
  strength: number
  /** Allies carry the lane they played most; matchups do not. */
  showPosition?: boolean
  /**
   * Gold difference at 14 minutes.
   *
   * Only meaningful for lane matchups. On the team and ally tables the same
   * number is this champion's gap against *their own laner* in games where the
   * listed champion happened to be present, which is not what a column headed
   * "Gold @14" next to a name reads as, so those tables leave it off.
   */
  showGold?: boolean
  /** Where a row's champion links, carrying the slice being read. */
  linkFor: (row: PairEntry) => string
}

/**
 * Both ways by the gap from the champion's own rate, as the draft reads the
 * same records: pulled toward that rate by a prior measured on these games,
 * and called favoured or unfavoured only when the record makes that 90%
 * likely. Ranked by the raw record instead, the hardest five lanes on the 31
 * busiest local pages were all level by this reading, and 22 of 155 sat at or
 * above the champion's own rate (2026-09-24).
 */
function ordered(rows: PairEntry[], order: PairOrder): PairEntry[] {
  return [...rows].sort(
    (a, b) => (order === 'worst' ? a.lift - b.lift : b.lift - a.lift) || b.games - a.games,
  )
}

const CALL_COLOUR: Record<PairEntry['call'], string> = {
  favoured: 'text-win',
  unfavoured: 'text-loss',
  level: 'text-ink-dim',
}

/** Counters and allies share a shape, so they share a table. */
export default function PairTable({
  title,
  hint,
  rows,
  order,
  query,
  championName,
  strength,
  showPosition,
  showGold,
  linkFor,
}: Props) {
  const [expanded, setExpanded] = useState(false)

  if (rows.length === 0) {
    return (
      <EmptyState
        title={`No ${title.toLowerCase()} yet`}
        body="No pairing in this slice has enough games yet. Lower 'Min games' above to see thinner records."
      />
    )
  }

  const needle = foldName(query)
  const all = ordered(rows, order)
  const matching = needle ? all.filter((r) => foldName(r.champion.name).includes(needle)) : all
  const shown = needle || expanded ? matching : matching.slice(0, SHOWN)
  const usual = rows[0].own_rate
  const gapHint =
    `How far each record sits from ${championName}'s usual ${pct(usual, 0)}, pulled toward it ` +
    `by a prior worth ${strength} games: a record of ${strength} games counts for half. It is ` +
    'called favoured or unfavoured only when the record makes that 90% likely.'

  return (
    // `min-w-0`: this sits in a grid on the Counters tab, and a grid item's
    // automatic minimum is its content's, so the table's floor widened the
    // page on a phone instead of scrolling inside the wrapper below.
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
          <table className="w-full min-w-[340px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-ink-faint">
                <th className="py-1.5 text-left font-500">Champion</th>
                <th className="py-1.5 text-right font-500">Record</th>
                <th className="py-1.5 pl-3 text-right font-500">
                  <Hint text={gapHint}>
                    <span
                      tabIndex={0}
                      className="cursor-help rounded-sm underline decoration-line decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
                    >
                      Against usual
                    </span>
                  </Hint>
                </th>
                {showGold && (
                  <th className="py-1.5 pl-3 text-right font-500">
                    <Hint
                      text={`${championName}'s gold lead over the listed laner at 14 minutes, from five or more games with a timeline.`}
                    >
                      <span
                        tabIndex={0}
                        className="cursor-help rounded-sm underline decoration-line decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
                      >
                        Gold @14
                      </span>
                    </Hint>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.champion.id} className="lift border-b border-line-soft">
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
                        <span className="text-xs text-ink-faint">{positionLabel(row.position)}</span>
                      )}
                    </Link>
                  </td>
                  <td className="tnum py-2 text-right">
                    <span className="block text-ink">
                      {row.wins}-{row.games - row.wins}
                    </span>
                    <span className="block text-[11px] text-ink-faint">{pct(row.win_rate, 0)}</span>
                  </td>
                  <td className="tnum py-2 pl-3 text-right">
                    <span className="sr-only">
                      {`${pct(row.win_rate, 0)} against the usual ${pct(row.own_rate, 0)}: ${CALL_WORD[row.call]}, `}
                    </span>
                    <span className={`block ${CALL_COLOUR[row.call]}`}>{points(row.lift)}</span>
                    <span aria-hidden className="block text-[11px] text-ink-faint">
                      {CALL_WORD[row.call]}
                    </span>
                  </td>
                  {showGold && (
                    <td className="tnum py-2 pl-3 text-right">
                      {row.avg_gold_diff_14 === null ? (
                        <span className="text-ink-faint">
                          <span aria-hidden>&ndash;</span>
                          <span className="sr-only">fewer than five games with a timeline</span>
                        </span>
                      ) : (
                        <span className={row.avg_gold_diff_14 >= 0 ? 'text-win' : 'text-loss'}>
                          {row.avg_gold_diff_14 >= 0 ? '+' : ''}
                          {Math.round(row.avg_gold_diff_14)}
                        </span>
                      )}
                    </td>
                  )}
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
