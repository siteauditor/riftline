import type { LiveGame } from '../../lib/api'
import { pct } from '../../lib/format'

export default function Notes({ game }: { game: LiveGame }) {
  const model = game.position_model
  return (
    <div className="max-w-prose space-y-1.5 text-xs leading-relaxed text-ink-faint">
      {model && (
        <p>
          Riot&apos;s live data has no positions, so each lane is inferred from the
          champions and their summoner spells, and a team&apos;s only Smite is always
          the jungler. Tested on {model.players_tested.toLocaleString()} players from
          our stored games that the model had not seen, it placed{' '}
          {pct(model.accuracy, 1)} of them correctly. A lane marked
          &ldquo;likely&rdquo; is one of the closer calls.
        </p>
      )}
      {game.corpus_patch && (
        <p>
          &ldquo;Champ WR&rdquo; and the lane records between opponents come from our
          stored games on patch {game.corpus_patch}, and appear only where there are
          enough of them. They describe the champions, not these players.
        </p>
      )}
      <p>
        Riot does not publish gold, items or K/D/A for a game in progress, to anyone.
        They arrive with the result, in the match history, once the game ends.
      </p>
      <p>
        Since 2025 players can hide their identity from third-party tools. Around a
        third of a typical lobby does, so anyone marked Hidden has no name, rank or
        mastery here, and the median above is taken over a sample rather than a
        census.
      </p>
    </div>
  )
}
