import type { MatchSummary } from '../../lib/api'
import { pct, winRateColor } from '../../lib/format'

/**
 * What this player has actually been playing, from the games on this page.
 *
 * Grouped from the same match window the rest of the idle view reads, so it
 * costs no request and its sample is one the reader can see: these are their
 * last twenty stored games, not a season.
 */
export default function RecentChampions({
  matches,
  max = 5,
}: {
  matches: MatchSummary[]
  max?: number
}) {
  const by = new Map<
    number,
    { name: string; icon: string | null; games: number; wins: number }
  >()
  for (const m of matches) {
    if (m.is_remake) continue
    const row = by.get(m.champion.id) ?? {
      name: m.champion.name,
      icon: m.champion.icon_url,
      games: 0,
      wins: 0,
    }
    row.games += 1
    if (m.win) row.wins += 1
    by.set(m.champion.id, row)
  }
  const champions = [...by.entries()]
    .sort((a, b) => b[1].games - a[1].games)
    .slice(0, max)

  if (champions.length === 0) return null

  return (
    <section className="frame px-4 py-3.5">
      <h2 className="eyebrow">What they have been playing</h2>
      <ul className="mt-2.5 space-y-2">
        {champions.map(([id, c]) => (
          <li key={id} className="flex items-center gap-2.5">
            {c.icon && <img src={c.icon} alt="" className="size-8 shrink-0" loading="lazy" />}
            <span className="min-w-0 flex-1 truncate text-sm text-ink">{c.name}</span>
            <span className="tnum shrink-0 text-xs text-ink-faint">
              {c.wins}-{c.games - c.wins}
            </span>
            <span
              className="tnum w-10 shrink-0 text-right text-sm font-600"
              style={{ color: winRateColor(c.wins / c.games, 0.6) }}
            >
              {pct(c.wins / c.games)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-[11px] text-ink-faint">
        Over their last {matches.filter((m) => !m.is_remake).length} stored games.
      </p>
    </section>
  )
}
