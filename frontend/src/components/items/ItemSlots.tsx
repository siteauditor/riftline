import type { ItemFigures } from '../../lib/api'
import { compact, pct } from '../../lib/format'
import { points, slotLabel } from './groups'

/**
 * How the item does as a player's 1st, 2nd, 3rd or later finished item,
 * against the other items the same champions bought at that point.
 *
 * Not a win rate. Win rate climbs from 28% for players who finished no items
 * to 62% for six, so a raw rate mostly says how late an item is bought. Items
 * in one slot share a game stage, which is what makes them comparable.
 */
export default function ItemSlots({ figures }: { figures: ItemFigures }) {
  if (figures.slots.length === 0) return null
  return (
    <section>
      <h2 className="display text-base font-600 text-ink">Against the same slot</h2>
      <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-faint">
        Each purchase is compared with the other items the same champions finished at the same
        point in their build. Shown from {figures.slot_min_games} purchases.
      </p>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full min-w-[22rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="py-1.5 text-left font-500">Bought as</th>
              <th className="py-1.5 text-left font-500">Share</th>
              <th className="py-1.5 text-right font-500">Games</th>
              <th className="py-1.5 text-right font-500" title="Points against the same slot">
                Against slot
              </th>
            </tr>
          </thead>
          <tbody>
            {figures.slots.map((s) => (
              <tr key={s.slot} className="border-b border-line-soft">
                <td className="py-1.5 text-ink">{slotLabel(s.slot)}</td>
                <td className="py-1.5">
                  <span className="flex items-center gap-2">
                    <span className="h-1.5 w-16 bg-raised" aria-hidden>
                      <span className="block h-full bg-ink-dim" style={{ width: `${s.share * 100}%` }} />
                    </span>
                    <span className="tnum text-xs text-ink-dim">{pct(s.share)}</span>
                  </span>
                </td>
                <td className="tnum py-1.5 text-right text-ink-faint">{compact(s.games)}</td>
                <td className="tnum py-1.5 text-right">
                  <Delta value={s.delta} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function Delta({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="text-xs text-ink-faint" title="Too few games to say">
        few games
      </span>
    )
  }
  return (
    <span
      className="font-600"
      style={{ color: value >= 0 ? 'var(--color-win)' : 'var(--color-loss)' }}
    >
      {points(value)}
    </span>
  )
}
