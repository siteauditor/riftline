import type { ChampionDetail, FacetEntry } from '../../lib/api'
import { EmptyState } from '../StateViews'
import { compact, pct } from '../../lib/format'

/**
 * Keystones and complete rune pages.
 *
 * A page id list is [primary tree, 4 primary perks, secondary tree, 2 secondary
 * perks, 3 stat shards]. Stat shards are not in Data Dragon's rune file, so they
 * come back without an icon and render as a dot rather than a broken image.
 */
export default function RunePanel({ runes }: { runes: ChampionDetail['runes'] }) {
  if (runes.keystones.length === 0 && runes.pages.length === 0) {
    return (
      <EmptyState
        title="No rune data yet"
        body="No rune setup in this slice clears the minimum sample. Lower 'min games', or ingest more matches."
      />
    )
  }

  return (
    <div className="space-y-5">
      {runes.keystones.length > 0 && (
        <section>
          <h3 className="mb-2 font-display text-sm font-700 text-ink">Keystones</h3>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {runes.keystones.map((entry) => (
              <RuneRow key={entry.ids.join()} entry={entry} />
            ))}
          </div>
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
                <RuneRow entry={entry} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function RuneRow({ entry }: { entry: FacetEntry }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 lift">
      {/* Allowed to shrink so it can wrap. A full page is eleven icons, 352px
          on one line, and pinned at that width it pushed the figures 71px off
          a 390px screen. */}
      <div className="flex min-w-0 flex-1 flex-wrap gap-1">
        {entry.runes.map((rune, i) => (
          <span
            key={`${rune.id}-${i}`}
            className="grid size-7 place-items-center rounded-full bg-raised"
          >
            {rune.icon_url ? (
              <img src={rune.icon_url} alt="" className="size-6" loading="lazy" />
            ) : (
              // Stat shard: Data Dragon has no icon for these.
              <span className="size-2 rounded-full bg-ink-faint" aria-hidden />
            )}
          </span>
        ))}
      </div>
      <div className="ml-auto shrink-0 text-right">
        <p
          className="tnum text-sm font-600"
          style={{
            color:
              entry.win_rate >= 0.55
                ? 'var(--color-gold-bright)'
                : entry.win_rate >= 0.5
                  ? 'var(--color-win)'
                  : 'var(--color-ink-dim)',
          }}
        >
          {pct(entry.win_rate, 1)}
        </p>
        <p className="tnum text-xs text-ink-faint">
          {compact(entry.games)} games, {pct(entry.pick_rate)}
        </p>
      </div>
    </div>
  )
}
