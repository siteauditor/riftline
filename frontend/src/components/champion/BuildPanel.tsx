import type { ReactNode } from 'react'

import type { ChampionDetail, FacetEntry } from '../../lib/api'
import ItemIcon from '../items/ItemIcon'
import { EmptyState } from '../StateViews'
import FacetRate from './FacetRate'
import { compact, pct } from '../../lib/format'

interface Props {
  builds: ChampionDetail['builds']
  spells: FacetEntry[]
  /** Carried to the item pages, so an item opens on the patch and queue read here. */
  itemSearch?: string
}

/**
 * The build path, the items most often finished, the finished builds, boots
 * and summoner spells.
 *
 * With timelines, the path is the first three completed items in the order
 * they were bought, and each item is set against the others the champion
 * bought in the same slot. Without them Riot's match data holds only the
 * final inventory, with items wherever they were left, so the panel says the
 * lists are what games ended with rather than inventing an order.
 */
export default function BuildPanel({ builds, spells, itemSearch = '' }: Props) {
  const empty =
    builds.complete.length === 0 &&
    builds.items.length === 0 &&
    builds.boots.length === 0 &&
    builds.path.length === 0

  if (empty) {
    return (
      <EmptyState
        title="No builds recorded yet"
        body="No build in this slice has enough games yet. Lower 'Min games' above to see thinner records."
      />
    )
  }

  return (
    <div className="space-y-5">
      {builds.basis === 'final_inventory' && (
        <p className="border-l-2 border-gold/50 py-1 pl-3 text-sm leading-relaxed text-ink-dim">
          These are the builds players <span className="text-ink">finished</span> games
          with, not the order they bought things in. Riot's match data records the
          final inventory, and none of these games has a timeline yet to give the
          order.
        </p>
      )}

      {builds.path.length > 0 && (
        <Section
          title="Build path"
          hint="The first three completed items, in the order they were actually bought."
        >
          <ul className="border-t border-line-soft">
            {builds.path.map((entry) => (
              <li key={entry.ids.join()}>
                <FacetRow itemSearch={itemSearch} entry={entry} wide ordered />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {builds.items.length > 0 && (
        <Section
          title="Most built items"
          hint="How often each item is finished, and how its buyers did against the other items this champion bought in the same slot, over every role. A finished inventory favours winners, who finish more items, so its own win rate is left out."
        >
          <ul className="grid border-t border-line-soft sm:grid-cols-2 lg:grid-cols-3">
            {builds.items.map((entry) => (
              <li key={entry.ids.join()}>
                <ItemRow itemSearch={itemSearch} entry={entry} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {builds.complete.length > 0 && (
        <Section
          title="Finished with three or more items"
          hint="Final inventories of games long enough to finish three items, most common first. Long games favour some items, so read the win rates with care."
        >
          <ul className="border-t border-line-soft">
            {builds.complete.map((entry) => (
              <li key={entry.ids.join()}>
                <FacetRow itemSearch={itemSearch} entry={entry} wide />
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {builds.boots.length > 0 && (
          <Section title="Boots">
            <div className="border-t border-line-soft">
              {builds.boots.map((entry) => (
                <FacetRow itemSearch={itemSearch} key={entry.ids.join()} entry={entry} wide />
              ))}
            </div>
          </Section>
        )}

        {spells.length > 0 && (
          <Section title="Summoner spells">
            <div className="border-t border-line-soft">
              {spells.map((entry) => (
                <FacetRow itemSearch={itemSearch} key={entry.ids.join()} entry={entry} wide />
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  )
}

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: ReactNode
}) {
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
        <h3 className="display text-base font-600 text-ink">{title}</h3>
        {hint && <p className="max-w-prose text-xs text-ink-faint">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

/** One item set, boot or spell pair, with its sample and result. */
function FacetRow({
  entry,
  wide,
  ordered,
  itemSearch = '',
}: {
  entry: FacetEntry
  wide?: boolean
  /** Draw arrows between icons, for a sequence rather than a set. */
  ordered?: boolean
  itemSearch?: string
}) {
  // Items link to their page in the item guide; summoner spells have none.
  const icons = [
    ...entry.items.map((ref) => ({ ref, item: true })),
    ...entry.spells.map((ref) => ({ ref, item: false })),
  ]
  const names = [...entry.items, ...entry.spells].map((r) => r.name).filter(Boolean)
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      <div className="flex shrink-0 gap-1">
        {icons.map(({ ref, item }, i) => (
          <span key={`${ref.id}-${i}`} className="flex items-center gap-1">
            {ordered && i > 0 && (
              <span className="text-xs text-ink-faint" aria-hidden>
                &rsaquo;
              </span>
            )}
            {item ? (
              <ItemIcon item={ref} size={28} className="rounded-sm bg-raised" search={itemSearch} />
            ) : (
              <span className="size-7 overflow-hidden rounded-sm bg-raised">
                {ref.icon_url && <img src={ref.icon_url} alt={ref.name ?? ''} loading="lazy" />}
              </span>
            )}
          </span>
        ))}
      </div>
      {wide && (
        <span className="min-w-0 flex-1 truncate text-xs text-ink-dim">
          {/* A path and a completed build can contain the same three items, so
              the separator is the only thing distinguishing them in text. */}
          {names.join(ordered ? ' › ' : ', ')}
        </span>
      )}
      <FacetRate entry={entry} />
    </div>
  )
}

/**
 * One item: how often it is finished, and how its buyers did against the
 * other items the champion bought in the same slot. The final inventory's own
 * win rate is not shown: winners finish more items, and on 16.18 items ran 2.3
 * points above their champion's own rate for that reason alone.
 */
function ItemRow({ entry, itemSearch }: { entry: FacetEntry; itemSearch: string }) {
  const item = entry.items[0]
  const delta = entry.slot_delta
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      {item && <ItemIcon item={item} size={28} className="shrink-0 rounded-sm bg-raised" search={itemSearch} />}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-ink">{item?.name ?? 'Unknown item'}</p>
        <p className="tnum text-xs text-ink-faint">
          In {pct(entry.pick_rate)} of games, {compact(entry.games)} in all
        </p>
      </div>
      <p className="tnum shrink-0 text-right text-xs">
        {delta !== null ? (
          <>
            <span className={`block text-sm font-600 ${delta >= 0 ? 'text-win' : 'text-loss'}`}>
              {delta >= 0 ? '+' : ''}
              {(delta * 100).toFixed(1)}
            </span>
            <span className="block text-ink-faint">vs its slot, {compact(entry.slot_buyers)} buyers</span>
          </>
        ) : (
          <span className="block max-w-[9rem] text-ink-faint">
            {entry.slot_buyers > 0
              ? `${entry.slot_buyers} buyers with a purchase order, too few to set against its slot`
              : 'No purchase order yet to set against its slot'}
          </span>
        )}
      </p>
    </div>
  )
}
