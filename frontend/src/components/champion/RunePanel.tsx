import type { ChampionDetail, FacetEntry } from '../../lib/api'
import { EmptyState } from '../StateViews'
import FacetRate from './FacetRate'

/**
 * Keystones and complete rune pages, named.
 *
 * A page id list is [primary tree, 4 primary perks, secondary tree, 2 secondary
 * perks, 3 stat shards]. Each rune carries its name, stat shards included, and
 * a page's runes are written out under its icons: the panel used to be eleven
 * unlabelled pictures a row, the shards grey dots.
 */
export default function RunePanel({ runes }: { runes: ChampionDetail['runes'] }) {
  if (runes.keystones.length === 0 && runes.pages.length === 0) {
    return (
      <EmptyState
        title="No rune data yet"
        body="No rune setup in this slice has enough games yet. Lower 'Min games' above to see thinner records."
      />
    )
  }

  return (
    <div className="space-y-5">
      {runes.keystones.length > 0 && (
        <section>
          <h3 className="mb-2 font-display text-sm font-700 text-ink">Keystones</h3>
          <ul className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 lg:grid-cols-3">
            {runes.keystones.map((entry) => (
              <li key={entry.ids.join()} className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
                <RuneIcon rune={entry.runes[0]} large />
                <span className="min-w-0 flex-1 truncate text-sm text-ink">
                  {entry.runes[0]?.name ?? 'Unknown rune'}
                </span>
                <FacetRate entry={entry} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {runes.pages.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Full pages</h3>
            <p className="text-xs text-ink-faint">
              Both trees and the three stat shards, most common first.
            </p>
          </div>
          <ul className="border-t border-line-soft">
            {runes.pages.map((entry) => (
              <li key={entry.ids.join()}>
                <PageRow entry={entry} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function RuneIcon({ rune, large }: { rune: FacetEntry['runes'][number] | undefined; large?: boolean }) {
  return (
    <span className={`grid shrink-0 place-items-center rounded-full bg-raised ${large ? 'size-9' : 'size-7'}`}>
      {rune?.icon_url ? (
        <img src={rune.icon_url} alt={rune.name ?? ''} className={large ? 'size-8' : 'size-6'} loading="lazy" />
      ) : (
        <span className="size-2 rounded-full bg-ink-faint" role="img" aria-label={rune?.name ?? 'Unknown rune'} />
      )}
    </span>
  )
}

/** The page's runes in words: the primary picks, the secondary picks, the shards. */
function pageWords(entry: FacetEntry): string {
  const names = entry.runes.map((r) => r.name ?? '?')
  // 0 and 5 are the trees themselves, which the picks already imply.
  const primary = names.slice(1, 5)
  const secondary = names.slice(6, 8)
  const shards = names.slice(8)
  return [primary, secondary, shards].map((part) => part.join(', ')).filter(Boolean).join('; ')
}

function PageRow({ entry }: { entry: FacetEntry }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      {/* Allowed to shrink so it can wrap. A full page is eleven icons, 352px
          on one line, and pinned at that width it pushed the figures 71px off
          a 390px screen. */}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap gap-1">
          {entry.runes.map((rune, i) => (
            <RuneIcon key={`${rune.id}-${i}`} rune={rune} />
          ))}
        </div>
        <p className="mt-1 text-xs leading-snug text-ink-dim">{pageWords(entry)}</p>
      </div>
      <FacetRate entry={entry} />
    </div>
  )
}
