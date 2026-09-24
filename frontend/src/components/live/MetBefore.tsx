import { Link } from 'react-router-dom'

import Hint from '../Hint'
import TimeAgo from '../TimeAgo'
import type { SharedGames } from '../../lib/api'
import { summonerPath } from '../../lib/profileAddress'

/**
 * Whether the searched player has met this one before.
 *
 * Measured 2026-09-21 over thirty recent stored lobbies: 23% of pairs share an
 * earlier stored match, and at least one pair had met in every one of the
 * thirty. Nobody else shows this, and it costs one indexed query.
 *
 * Always counts, never a percentage: these are single digit samples, and a
 * "67% against them" over three games is exactly the kind of figure that gets
 * quoted back as though it meant something. The wording stays on the games we
 * hold rather than on the people, because the crawler walks outward from stored
 * matches and what it holds is not a census of anybody's history.
 */
export default function MetBefore({
  shared,
  platform,
  name,
  tag,
}: {
  shared: SharedGames | null
  /** Where to send the reader for the games themselves. */
  platform: string
  name: string
  tag: string
}) {
  if (!shared || shared.games === 0) return null

  const times = shared.games === 1 ? 'once' : `${shared.games} times`
  const against =
    shared.opposite_side > 0
      ? `${shared.opposite_side_wins}-${shared.opposite_side - shared.opposite_side_wins} against them`
      : null
  const beside =
    shared.same_side > 0
      ? `${shared.same_side_wins}-${shared.same_side - shared.same_side_wins} together`
      : null

  return (
    <Hint
      text={
        <>
          You and this player were both in {shared.games} stored{' '}
          {shared.games === 1 ? 'game' : 'games'}: {shared.same_side} on the same side and{' '}
          {shared.opposite_side} against each other
          {shared.last_played && (
            <>
              , most recently <TimeAgo at={shared.last_played} />
            </>
          )}
          . These are the games Riftline holds, not everything either of you has played.
        </>
      }
    >
      <Link
        to={summonerPath(platform, name, tag)}
        className="whitespace-nowrap text-[11px] text-ink-dim underline decoration-line underline-offset-2 transition-colors hover:text-gold-bright"
      >
        Met {times}
        {(against || beside) && `, ${[against, beside].filter(Boolean).join(', ')}`}
      </Link>
    </Hint>
  )
}
