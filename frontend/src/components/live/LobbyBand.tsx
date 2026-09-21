import type { CSSProperties } from 'react'

import type { LobbyRank } from '../../lib/api'
import { tierColor, tierLabel } from '../../lib/format'

export default function LobbyBand({ lobby }: { lobby: LobbyRank }) {
  const counted = [
    lobby.hidden > 0 && `${lobby.hidden} hid their identity`,
    lobby.unranked > 0 && `${lobby.unranked} unranked`,
    lobby.unknown > 0 && `${lobby.unknown} could not be looked up`,
    lobby.bots > 0 && `${lobby.bots} bots`,
  ].filter(Boolean) as string[]

  if (lobby.median_points === null) {
    return (
      <section className="accent-edge bg-panel/50 py-2.5 pl-4">
        <h3 className="display text-lg font-600 text-ink">
          Not enough identified players
        </h3>
        <p className="mt-1 text-xs text-ink-faint">
          Only {lobby.ranked} {lobby.ranked === 1 ? 'player' : 'players'} in this
          lobby {lobby.ranked === 1 ? 'exposes' : 'expose'} a rank
          {counted.length > 0 && `. ${counted.join(', ')}`}.
        </p>
      </section>
    )
  }

  const accent = tierColor(lobby.tier)
  return (
    // A band in the lobby's own colour rather than a card: this is the headline
    // measurement of the page, and the tier colour is how it is read first.
    <section
      className="accent-edge bg-panel/50 py-2.5 pl-4"
      style={{ '--accent': accent } as CSSProperties}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm text-ink-dim">Median rank</h3>
        <p className="display text-2xl font-700" style={{ color: accent }}>
          {tierLabel(lobby.tier, lobby.division)}
          {lobby.league_points != null && (
            <span className="tnum ml-2 text-base font-600 text-ink-dim">
              {lobby.league_points.toLocaleString()} LP
            </span>
          )}
        </p>
      </div>
      <p className="mt-1.5 text-xs text-ink-faint">
        Median of {lobby.ranked} identified{' '}
        {lobby.ranked === 1 ? 'player' : 'players'}
        {counted.length > 0 && `. ${counted.join(', ')}`}.
        {!lobby.queue_matches_game &&
          ' Solo queue rank is shown, because this queue has no rank of its own.'}
      </p>
    </section>
  )
}
