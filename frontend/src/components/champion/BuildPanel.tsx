import type { ReactNode } from 'react'

import type { ChampionDetail, FacetEntry } from '../../lib/api'
import { EmptyState } from '../StateViews'
import { compact, pct, winRateColor } from '../../lib/format'

interface Props {
  builds: ChampionDetail['builds']
  spells: FacetEntry[]
}

/**
 * Completed builds, individual items, boots and summoner spells.
 *
 * The caveat at the top is not boilerplate. Riot's match data records a
 * player's *final inventory*, with items sitting wherever they were left, so
 * there is no purchase order in it to report. Every other site shows an ordered
 * build path because it reads match timelines, which we do not fetch yet.
 * Presenting these as a path would be inventing data.
 */
export default function BuildPanel({ builds, spells }: Props) {
  const empty =
    builds.complete.length === 0 &&
    builds.items.length === 0 &&
    builds.boots.length === 0 &&
    builds.path.length === 0

  if (empty) {
    return (
      <EmptyState
        title="No builds recorded yet"
        body="No build in this slice clears the minimum sample. Lower 'min games', or ingest more matches."
      />
    )
  }

  return (
    <div className="space-y-5">
      {builds.basis === 'final_inventory' && (
        <p className="border-l-2 border-gold/50 py-1 pl-3 text-sm leading-relaxed text-ink-dim">
          These are the builds players <span className="text-ink">finished</span> games
          with, not the order they bought things in. Riot's match data records the
          final inventory, and the slots carry no purchase order. Fetch match
          timelines and a real build order appears here.
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
                <FacetRow entry={entry} wide ordered />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {builds.items.length > 0 && (
        <Section title="Most built items" hint="Counted individually, so this survives a small sample best.">
          <div className="grid grid-cols-2 border-t border-line-soft sm:grid-cols-3 lg:grid-cols-4">
            {builds.items.map((entry) => (
              <FacetRow key={entry.ids.join()} entry={entry} />
            ))}
          </div>
        </Section>
      )}

      {builds.complete.length > 0 && (
        <Section title="Completed builds" hint="The full set of finished items, most common first.">
          <ul className="border-t border-line-soft">
            {builds.complete.map((entry) => (
              <li key={entry.ids.join()}>
                <FacetRow entry={entry} wide />
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
                <FacetRow key={entry.ids.join()} entry={entry} />
              ))}
            </div>
          </Section>
        )}

        {spells.length > 0 && (
          <Section title="Summoner spells">
            <div className="border-t border-line-soft">
              {spells.map((entry) => (
                <FacetRow key={entry.ids.join()} entry={entry} />
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
        {hint && <p className="text-xs text-ink-faint">{hint}</p>}
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
}: {
  entry: FacetEntry
  wide?: boolean
  /** Draw arrows between icons, for a sequence rather than a set. */
  ordered?: boolean
}) {
  const icons = [...entry.items, ...entry.spells]
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      <div className="flex shrink-0 gap-1">
        {icons.map((ref, i) => (
          <span key={`${ref.id}-${i}`} className="flex items-center gap-1">
            {ordered && i > 0 && (
              <span className="text-xs text-ink-faint" aria-hidden>
                &rsaquo;
              </span>
            )}
            <span
              className="size-7 overflow-hidden rounded-sm bg-raised"
              title={ref.name ?? ''}
            >
              {ref.icon_url && (
                <img src={ref.icon_url} alt={ref.name ?? ''} loading="lazy" />
              )}
            </span>
          </span>
        ))}
      </div>
      {wide && (
        <span className="min-w-0 flex-1 truncate text-xs text-ink-dim">
          {/* A path and a completed build can contain the same three items, so
              the separator is the only thing distinguishing them in text. */}
          {entry.items
            .map((i) => i.name)
            .filter(Boolean)
            .join(ordered ? ' › ' : ', ')}
        </span>
      )}
      <div className="ml-auto shrink-0 text-right">
        <p className="tnum text-sm font-600" style={{ color: winRateColor(entry.win_rate) }}>
          {pct(entry.win_rate, 1)}
        </p>
        <p className="tnum text-xs text-ink-faint">
          {compact(entry.games)} games, {pct(entry.pick_rate)}
        </p>
      </div>
    </div>
  )
}
