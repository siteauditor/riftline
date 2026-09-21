import type { LiveGame } from '../../lib/api'
import { pct } from '../../lib/format'

export default function Notes({ game }: { game: LiveGame }) {
  const model = game.position_model
  return (
    <details className="max-w-prose text-xs leading-relaxed text-ink-faint">
      <summary className="cursor-pointer text-ink-dim">
        How this page reads the lobby
      </summary>
      <div className="mt-2 space-y-1.5">
      {model && (
        <p>
          Each lane is inferred from the champions and their summoner spells, and
          a team&apos;s only Smite is always the jungler. The{' '}
          {pct(model.accuracy, 1)} above was measured on{' '}
          {model.players_tested.toLocaleString()} players from our stored games
          that the model had not seen. A lane marked &ldquo;likely&rdquo; is one
          of the closer calls, and those are right about half to two thirds of
          the time.
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
        A lane record with no games on this patch falls back to the patch before
        it, and then to games where both champions were in the lobby rather than
        in the same lane. Anything below a lane record on this patch says so
        under the bar.
      </p>
      <p>
        A player&apos;s own figures are the games Riftline has stored for them,
        which is not their season. We hold nothing for someone outside the part
        of the ladder we crawl, and the card says so rather than guessing.
      </p>
      <p>
        Since 2025 players can hide their identity from third-party tools. Around a
        third of a typical lobby does, so anyone marked Hidden has no name, rank or
        mastery here, and the median above is taken over a sample rather than a
        census.
      </p>
      </div>
    </details>
  )
}
