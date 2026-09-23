import { Link } from 'react-router-dom'

import type { ItemFigures } from '../../lib/api'
import { compact, pct } from '../../lib/format'
import type { ItemSlice } from '../../lib/queries'
import { championPath } from '../../lib/searchParams'
import { slotLabel } from './groups'
import { Delta } from './ItemSlots'

/** Who buys it: the champions with the most purchases, and how it does for each. */
export default function ItemChampions({
  figures,
  finished,
  slice,
}: {
  figures: ItemFigures
  finished: boolean
  /** The slice being read, carried to each champion's page. */
  slice?: ItemSlice
}) {
  if (figures.champions.length === 0) return null
  return (
    <section>
      <h2 className="display text-base font-600 text-ink">Who buys it</h2>
      <p className="mt-1 max-w-prose text-xs leading-relaxed text-ink-faint">
        The share is of that champion's games with a timeline.
        {finished &&
          ` "Against slot" compares it with the champion's other items bought at the same point, from ${figures.champion_min_buyers} purchases.`}
      </p>
      <div className="overflow-x-auto">
        <table className="mt-2 w-full min-w-[20rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="py-1.5 text-left font-500">Champion</th>
              <th className="py-1.5 text-right font-500">Bought</th>
              <th className="py-1.5 text-right font-500">Share</th>
              {finished && <th className="hidden py-1.5 text-right font-500 sm:table-cell">Usually</th>}
              {/* Off on a phone, where the table otherwise ran past 390px and
                  pushed "Against slot" out of view. */}
              <th className="hidden py-1.5 text-right font-500 sm:table-cell">Minute</th>
              {finished && <th className="py-1.5 text-right font-500">Against slot</th>}
            </tr>
          </thead>
          <tbody>
            {figures.champions.map((c) => (
              <tr key={c.champion.id} className="lift border-b border-line-soft">
                <td className="py-1.5">
                  <Link to={championPath(c.champion, null, slice)} className="group flex items-center gap-2">
                    {c.champion.icon_url && (
                      <img
                        src={c.champion.icon_url}
                        alt=""
                        loading="lazy"
                        className="size-7 ring-1 ring-line group-hover:ring-gold"
                      />
                    )}
                    <span className="display truncate text-[15px] font-600 text-ink group-hover:text-gold-bright">
                      {c.champion.name}
                    </span>
                  </Link>
                </td>
                <td className="tnum py-1.5 text-right text-ink-dim">{compact(c.buyers)}</td>
                <td className="tnum py-1.5 text-right text-ink-dim">{pct(c.share)}</td>
                {finished && (
                  <td className="hidden py-1.5 text-right text-xs text-ink-faint sm:table-cell">
                    {c.usual_slot ? slotLabel(c.usual_slot) : ''}
                  </td>
                )}
                <td className="tnum hidden py-1.5 text-right text-ink-faint sm:table-cell">
                  {c.minute !== null ? c.minute.toFixed(0) : ''}
                </td>
                {finished && (
                  <td className="tnum py-1.5 text-right">
                    <Delta value={c.delta} />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
