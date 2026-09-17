import type { CSSProperties } from 'react'

import type { RankInfo } from '../lib/api'
import { pct, tierColor, tierLabel } from '../lib/format'

/**
 * A ranked queue at a glance.
 *
 * No emblem art: the tier's own colour does the identifying work, which keeps
 * the card readable at any size and avoids depending on scraped Riot assets.
 * The win/loss bar is the honest version of a win rate -- it shows sample size
 * and split in the same object.
 */
export default function RankCard({ rank }: { rank: RankInfo }) {
  const color = tierColor(rank.tier)
  const ranked = Boolean(rank.tier)

  return (
    // The rule carries this queue's own tier, which is not always the one the
    // page header shows: plenty of players are two tiers apart in solo and flex.
    <section
      className="accent-edge rounded-r-sm border-y border-r border-line bg-panel"
      style={{ '--accent': color } as CSSProperties}
    >
      <header className="flex items-center justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="display text-sm font-600 text-ink-dim">{rank.queue_label}</h2>
        {rank.hot_streak && (
          <span className="rounded-sm bg-gold/15 px-1.5 py-0.5 text-[11px] font-600 text-gold-bright">
            Hot streak
          </span>
        )}
      </header>

      <div className="px-4 py-3.5">
        {ranked ? (
          <>
            <p
              className="display text-[28px] font-700 leading-none"
              style={{ color }}
            >
              {tierLabel(rank.tier, rank.division)}
            </p>

            <p className="mt-1.5 text-sm text-ink-dim">
              <span className="tnum font-600 text-ink">
                {rank.league_points.toLocaleString()}
              </span>{' '}
              LP
            </p>

            <div className="mt-3.5">
              <div className="flex h-1.5 overflow-hidden rounded-full bg-raised">
                <div
                  className="bg-win"
                  style={{ width: `${rank.win_rate * 100}%` }}
                  aria-hidden
                />
                <div className="flex-1 bg-loss/70" aria-hidden />
              </div>
              <div className="mt-1.5 flex justify-between text-xs text-ink-dim">
                <span className="tnum">
                  <span className="text-win">{rank.wins}W</span>
                  <span className="mx-1 text-ink-faint">/</span>
                  <span className="text-loss">{rank.losses}L</span>
                </span>
                <span className="tnum">{pct(rank.win_rate)}</span>
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-ink-faint">Unranked this season</p>
        )}
      </div>
    </section>
  )
}
