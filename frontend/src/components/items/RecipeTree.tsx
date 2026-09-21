import { useState } from 'react'

import type { ItemDetail, ItemRefCost } from '../../lib/api'
import ItemIcon from './ItemIcon'

// A component can build into thirty items; the first few, cheapest first,
// say what it is for, and the rest are one click away.
const INTO_SHOWN = 8

/**
 * What an item is built from and what it builds into, with costs, and the
 * growth an item goes through without being bought (Manamune into Muramana).
 */
export default function RecipeTree({ item }: { item: ItemDetail }) {
  const [allInto, setAllInto] = useState(false)
  const into = allInto ? item.builds_into : item.builds_into.slice(0, INTO_SHOWN)
  const nothing =
    !item.builds_from.length && !item.builds_into.length && !item.grows_from && !item.grows_into.length
  if (nothing) return null

  return (
    <section>
      <h2 className="display text-base font-600 text-ink">Recipe</h2>
      {/* One list under the other: the page's left column is narrow, and side
          by side the names of three-part recipes truncated. */}
      <div className="mt-2 space-y-5">
        {item.builds_from.length > 0 && (
          <div>
            <p className="text-xs text-ink-faint">Built from</p>
            <ul className="mt-1.5 space-y-1">
              {item.builds_from.map((ref, i) => (
                <RecipeRow key={`${ref.id}-${i}`} item={ref} />
              ))}
            </ul>
            {item.combine_cost > 0 && (
              <p className="tnum mt-1.5 text-xs text-ink-faint">
                plus {item.combine_cost.toLocaleString('en-US')} gold to combine
              </p>
            )}
          </div>
        )}
        {item.builds_into.length > 0 && (
          <div>
            <p className="text-xs text-ink-faint">Builds into</p>
            <ul className="mt-1.5 space-y-1">
              {into.map((ref) => (
                <RecipeRow key={ref.id} item={ref} />
              ))}
            </ul>
            {item.builds_into.length > INTO_SHOWN && (
              <button
                type="button"
                onClick={() => setAllInto(!allInto)}
                className="mt-1.5 text-xs text-ink-dim underline decoration-line underline-offset-2 hover:text-gold-bright"
              >
                {allInto ? 'Show fewer' : `Show all ${item.builds_into.length}`}
              </button>
            )}
          </div>
        )}
      </div>
      {item.grows_into.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink-dim">
          Grows into
          {item.grows_into.map((ref) => (
            <GrowthLink key={ref.id} item={ref} />
          ))}
          once its charge is complete.
        </p>
      )}
      {item.grows_from && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-ink-dim">
          Grows out of <GrowthLink item={item.grows_from} /> once its charge is complete.
        </p>
      )}
    </section>
  )
}

function RecipeRow({ item }: { item: ItemRefCost }) {
  return (
    <li className="flex items-center gap-2.5">
      <ItemIcon item={item} size={28} className="ring-1 ring-line" />
      <span className="min-w-0 flex-1 truncate text-sm text-ink">{item.name}</span>
      <span className="tnum text-xs text-ink-faint">{item.cost.toLocaleString('en-US')}</span>
    </li>
  )
}

function GrowthLink({ item }: { item: ItemRefCost }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <ItemIcon item={item} size={22} className="ring-1 ring-line" />
      <span className="font-600 text-ink">{item.name}</span>
    </span>
  )
}
