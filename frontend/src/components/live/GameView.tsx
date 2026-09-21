import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import Bans from './Bans'
import LaneView from './LaneView'
import LobbyBand from './LobbyBand'
import Notes from './Notes'
import TeamView from './TeamView'
import type { LiveGame } from '../../lib/api'
import { duration } from '../../lib/format'

export default function GameView({
  game,
  platform,
  you,
  stale,
  ended = false,
  poll,
}: {
  game: LiveGame
  platform: string
  you: string
  stale: boolean
  ended?: boolean
  /** The countdown and the check button, owned by the page that polls. */
  poll?: ReactNode
}) {
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="display text-2xl font-700 text-ink">{game.queue_name}</h2>
        {ended ? (
          <span className="text-sm text-ink-dim">Ended</span>
        ) : (
          <GameClock game={game} />
        )}
        {!game.you_identified && (
          <span className="text-xs text-ink-faint">
            This player hides their identity, so their own row is not marked
          </span>
        )}
        {stale && (
          <span className="text-xs text-loss">
            Could not refresh; showing the last successful check
          </span>
        )}
        {poll && <span className="ml-auto">{poll}</span>}
      </header>

      <LobbyBand game={game} you={you} />

      {/* During champion select the picks are locked but nothing has happened
          yet, so the bans are the only settled information the lobby has. They
          move above the lanes until the game starts. */}
      {game.phase === 'loading' && <Bans game={game} />}

      {game.positions_inferred ? (
        <LaneView game={game} platform={platform} you={you} />
      ) : (
        <TeamView game={game} platform={platform} you={you} />
      )}

      {game.phase !== 'loading' && <Bans game={game} />}
      <Notes game={game} />
    </div>
  )
}

/**
 * The clock runs locally from `observed_at`, rather than polling the server for
 * a number it can work out itself.
 */
function GameClock({ game }: { game: LiveGame }) {
  // Counted from when *this browser* received the payload, not differenced
  // against the server's wall clock. `Date.now() - observed_at` measures the
  // skew between the two machines, which is routinely tens of seconds: a
  // browser running behind pinned the delta at zero and the timer sat frozen
  // between polls, and one running ahead read permanently too high.
  const [elapsed, setElapsed] = useState(game.game_length)

  useEffect(() => {
    const receivedAt = Date.now()
    const base = game.game_length
    const id = setInterval(
      () => setElapsed(base + (Date.now() - receivedAt) / 1000),
      1000,
    )
    return () => clearInterval(id)
  }, [game.observed_at, game.game_length])

  if (game.phase === 'loading') {
    return <span className="text-sm text-gold-bright">Champion select</span>
  }
  return (
    <span className="tnum text-sm text-ink-dim">
      {duration(Math.max(0, Math.floor(elapsed)))}
    </span>
  )
}
