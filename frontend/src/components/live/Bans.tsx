import type { LiveGame } from '../../lib/api'
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
                className="size-7 overflow-hidden rounded-sm bg-raised grayscale"
                title={b.champion.name}
              >
                {b.champion.icon_url && (
                  <img src={b.champion.icon_url} alt={b.champion.name} loading="lazy" />
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
