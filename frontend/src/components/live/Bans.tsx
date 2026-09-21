import type { LiveGame } from '../../lib/api'
import { pct } from '../../lib/format'
import { BLUE, RED } from './sides'

export default function Bans({ game }: { game: LiveGame }) {
  if (game.bans.length === 0) return null
  const sided = game.positions_inferred
  const groups = sided
    ? [
        { key: BLUE, label: 'Blue bans', color: 'var(--color-win)', bans: game.bans.filter((b) => b.team_id === BLUE) },
        { key: RED, label: 'Red bans', color: 'var(--color-loss)', bans: game.bans.filter((b) => b.team_id === RED) },
      ]
    : [{ key: 0, label: 'Bans', color: 'var(--color-ink)', bans: game.bans }]

  // Beside the lanes they belong to: blue's pulled in towards the middle from
  // the left and red's from the right, the same way the lane cards are.
  return (
    <section
      className={`grid gap-3 ${sided ? 'grid-cols-2 gap-x-[4.5rem] sm:gap-x-[7.5rem]' : ''}`}
    >
      {groups.map((g, i) => (
        <div key={g.key} className={sided && i === 0 ? 'text-right' : ''}>
          <h3 className="mb-2 display text-sm font-600" style={{ color: g.color }}>
            {g.label}
          </h3>
          <div className={`flex flex-wrap gap-1 ${sided && i === 0 ? 'justify-end' : ''}`}>
            {g.bans.map((b, j) => (
              <span
                key={`${b.champion.id}-${j}`}
                className="w-9 shrink-0 text-center"
                title={
                  b.ban_rate === null
                    ? `${b.champion.name}, banned. We hold too few games of them on this patch to say how often that happens.`
                    : `${b.champion.name} is banned in ${pct(b.ban_rate, 1)} of the ${(b.ban_rate_games ?? 0).toLocaleString()} games we hold on this patch.`
                }
              >
                <span className="block size-9 overflow-hidden bg-raised grayscale">
                  {b.champion.icon_url && (
                    <img src={b.champion.icon_url} alt={b.champion.name} loading="lazy" />
                  )}
                </span>
                {/* Bans are the only settled information during champion
                    select, so each one says how usual it is. */}
                {b.ban_rate != null && (
                  <span className="tnum mt-0.5 block text-[10px] leading-none text-ink-faint">
                    {pct(b.ban_rate)}
                  </span>
                )}
              </span>
            ))}
            {g.bans.length === 0 && <span className="text-xs text-ink-faint">None</span>}
          </div>
        </div>
      ))}
    </section>
  )
}
