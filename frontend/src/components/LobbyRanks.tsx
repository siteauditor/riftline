import Hint from './Hint'
import type { MetaResponse } from '../lib/api'
import { pct, shortDate, tierColor, tierLabel } from '../lib/format'

type Lobby = NonNullable<MetaResponse['lobby_ranks']>

/**
 * Who the games behind a list were: each lobby's measured median rank.
 *
 * Measured, not assumed. The crawler starts from the top of the ladder, so on
 * 16.18 95% of the games were Master+ lobbies, and a Gold player reading a tier
 * list or a draft should know that. Riot keeps no historical rank, so the
 * measurement is where those players stood on the day it was taken, which the
 * line says.
 *
 * The headline names the largest bucket. It named the first, and the buckets
 * come highest first, so it read "Master+" for a corpus that was mostly Gold
 * the day it stopped being mostly Master+.
 */
export default function LobbyRanks({ lobby, className = 'mt-3' }: { lobby: Lobby; className?: string }) {
  if (lobby.measured === 0 || lobby.buckets.length === 0) return null
  const largest = lobby.buckets.reduce((a, b) => (b.games > a.games ? b : a))
  const label = (tier: string) => (tier === 'MASTER+' ? 'Master+' : tierLabel(tier))
  const colour = (tier: string) => tierColor(tier === 'MASTER+' ? 'MASTER' : tier)
  const measuredOn = lobby.as_of ? shortDate(lobby.as_of) : null
  return (
    <div className={`${className} flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink-dim`}>
      <span className="flex h-1.5 w-32 overflow-hidden rounded-full bg-raised" aria-hidden>
        {lobby.buckets.map((b) => (
          <span
            key={b.tier}
            style={{ width: `${(b.games / lobby.measured) * 100}%`, background: colour(b.tier) }}
          />
        ))}
      </span>
      <Hint text={lobby.buckets.map((b) => `${label(b.tier)}: ${b.games}`).join(', ')}>
        <span tabIndex={0}>
          <span className="tnum text-ink">{pct(largest.games / lobby.measured)}</span> of these
          games were {label(largest.tier)} lobbies
          <span className="text-ink-faint">
            {' '}
            ({lobby.measured.toLocaleString('en-US')} of {lobby.total.toLocaleString('en-US')} measured)
          </span>
        </span>
      </Hint>
      <span className="text-ink-faint">
        Median rank of each lobby
        {measuredOn ? `, measured ${measuredOn}` : ''}, not when the games were played.
      </span>
    </div>
  )
}
