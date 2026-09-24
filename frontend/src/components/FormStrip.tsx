import { useMemo, useState } from 'react'

import type { MatchSummary, QueueScope } from '../lib/api'
import { scopeNoun } from '../lib/profileScope'
import {
  duration,
  ordinal,
  positionLabel,
  scoreColor,
} from '../lib/format'
import TimeAgo from './TimeAgo'
import { gameAnchor } from '../lib/profileAddress'
import Hint from './Hint'

/**
 * Recent form as a rhythm.
 *
 * Every other stats site renders history as a uniform list, which makes a good
 * run and a bad run look identical until you read twenty rows of numbers. Here
 * each game is one bar: colour is the result, height is how much the player did
 * in it. A streak, a slump, or a smurf is visible in one glance.
 *
 * Height is the Riftline score, which is what this strip was always reaching
 * for: a single figure for how much a game was worth. It falls back to KDA on
 * any game the score is withheld for (ARAM, Arena, a remake), because a bar of
 * zero height would read as a terrible game rather than an unmeasured one, and
 * the footer says which of the two it is showing.
 *
 * Either way the scale is fixed rather than normalised to the sample, so the
 * shape means the same thing between two different players.
 */

const KDA_CEILING = 8
const SCORE_CEILING = 10

interface Props {
  matches: MatchSummary[]
  /** The queues the list covers, for the heading. */
  scope?: QueueScope | null
  /** A bar picked: the page opens that game's row below. */
  onPick?: (matchId: string) => void
}

export default function FormStrip({ matches, scope, onPick }: Props) {
  const [hovered, setHovered] = useState<number | null>(null)

  // Oldest on the left: the strip reads as a timeline.
  const games = useMemo(
    () => matches.filter((m) => !m.is_remake).slice().reverse(),
    [matches],
  )

  // Scored games in this window, which decides what the bars mean.
  const scored = useMemo(
    () => games.filter((g) => g.score !== null).length,
    [games],
  )

  const summary = useMemo(() => {
    const wins = games.filter((g) => g.win).length
    const kills = games.reduce((n, g) => n + g.kills, 0)
    const deaths = games.reduce((n, g) => n + g.deaths, 0)
    const assists = games.reduce((n, g) => n + g.assists, 0)
    return {
      wins,
      losses: games.length - wins,
      kda: deaths === 0 ? kills + assists : (kills + assists) / deaths,
    }
  }, [games])

  if (games.length === 0) return null

  const active = hovered !== null ? games[hovered] : null

  return (
    <section
      aria-label="Recent form"
      className="frame px-4 py-3.5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="display text-base font-600 text-ink">
          Last {games.length} {scopeNoun(scope) ? `${scopeNoun(scope)} ` : ''}
          {games.length === 1 ? 'game' : 'games'}
        </h2>
        {/* Wins and losses, and no percentage: over twenty games one game
            moves it five points, which reads as a trend and is not one. */}
        <div className="flex items-baseline gap-3 text-xs text-ink-dim">
          <span>
            <span className="tnum text-win">{summary.wins}W</span>
            <span className="mx-1 text-ink-faint">/</span>
            <span className="tnum text-loss">{summary.losses}L</span>
          </span>
          <span className="tnum">{summary.kda.toFixed(2)} KDA</span>
        </div>
      </div>

      {/* 48px on a phone: every pixel above the first game counts there. */}
      <div className="mt-3 flex h-12 items-end gap-[3px] sm:h-16">
        {games.map((game, i) => {
          const kda =
            game.deaths === 0 ? KDA_CEILING : (game.kills + game.assists) / game.deaths
          const fraction =
            game.score !== null
              ? game.score / SCORE_CEILING
              : kda / KDA_CEILING
          const height = Math.max(0.12, Math.min(1, fraction))
          const isActive = hovered === i
          return (
            <button
              key={game.match_id}
              type="button"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(i)}
              onBlur={() => setHovered(null)}
              onClick={() => onPick?.(game.match_id)}
              aria-controls={onPick ? gameAnchor(game.match_id) : undefined}
              aria-label={
                `${game.win ? 'Win' : 'Loss'} as ${game.champion.name}, ` +
                `${game.kills}/${game.deaths}/${game.assists}` +
                (game.score !== null ? `, scored ${game.score.toFixed(1)}` : '')
              }
              className="group relative flex h-full flex-1 items-end"
            >
              <span
                className="w-full rounded-t-[2px] transition-[height,opacity] duration-200"
                style={{
                  height: `${height * 100}%`,
                  background: game.win ? 'var(--color-win)' : 'var(--color-loss)',
                  opacity: hovered === null || isActive ? 1 : 0.45,
                }}
              />
            </button>
          )
        })}
      </div>

      {/* Reserved height keeps the panel from resizing as you sweep across. */}
      <div className="mt-2.5 flex h-6 items-center gap-2 border-t border-line-soft pt-2 text-xs">
        {active ? (
          <>
            {active.champion.icon_url && (
              <img
                src={active.champion.icon_url}
                alt=""
                className="size-5 rounded-sm"
                loading="lazy"
              />
            )}
            <span className="font-500 text-ink">{active.champion.name}</span>
            <span className="tnum text-ink-dim">
              {active.kills}/{active.deaths}/{active.assists}
            </span>
            <span className={active.win ? 'text-win' : 'text-loss'}>
              {active.win ? 'Win' : 'Loss'}
            </span>
            {active.score !== null && (
              <Hint text={`Riftline score, ${ordinal(active.placement ?? 0)} of ten in that lobby`}>
                <span tabIndex={0} className="tnum font-600 outline-none" style={{ color: scoreColor(active.score) }}>
                  {active.score.toFixed(1)}
                </span>
              </Hint>
            )}
            <span className="text-ink-faint">
              {positionLabel(active.position)}, {duration(active.game_duration)},{' '}
              <TimeAgo at={active.game_creation} />
            </span>
          </>
        ) : (
          <span className="text-ink-faint">
            {scored === games.length
              ? 'Bar height is the Riftline score.'
              : scored === 0
                ? 'Bar height is KDA: none of these games can be scored.'
                : `Bar height is the Riftline score, or KDA on the ${
                    games.length - scored
                  } game${games.length - scored === 1 ? '' : 's'} it is withheld for.`}
            {onPick ? ' Pick a bar to open that game.' : ''}
          </span>
        )}
      </div>
    </section>
  )
}
