import Hint from '../Hint'
import TimeAgo from '../TimeAgo'
import type { LiveParticipant } from '../../lib/api'
import { pct, positionLabel, scoreColor, winRateColor } from '../../lib/format'

/**
 * What this player has done, as opposed to what their champion does.
 *
 * Until this existed the lobby showed rank, mastery and the champion's win
 * rate, so nothing on the page was about the people in it. Measured 2026-09-21:
 * a median of 9 of 10 players in a stored lobby have three or more other stored
 * games, so these chips are filled in for almost everyone in a bracket we
 * crawl, and empty for anyone outside it.
 *
 * Every figure carries its sample in its hint, and a record we hold too little
 * of is absent rather than small: "we hold two games" is said in words, because
 * a 2-0 rendered as 100% is the kind of number that gets quoted back.
 */
export default function PlayerRecordChips({
  p,
  championName,
  dense = false,
}: {
  p: LiveParticipant
  championName: string
  /** The lobby rows, where there is room for one line rather than two. */
  dense?: boolean
}) {
  const record = p.record
  if (!record) {
    // Nothing held is worth saying once, quietly. A hidden player has no puuid
    // at all, so there is nothing to look up and nothing to report.
    if (p.state === 'hidden' || p.state === 'bot' || p.stored_games === 0) return null
    return (
      <Hint
        text={`We hold ${p.stored_games} stored ${p.stored_games === 1 ? 'game' : 'games'} for this player, which is too few to describe how they play.`}
      >
        <span tabIndex={0} className="text-[11px] text-ink-faint">
          {p.stored_games} stored
        </span>
      </Hint>
    )
  }

  const { overall, on_champion: champ } = record

  return (
    <>
      <Hint
        text={
          <>
            {overall.games} stored games: {overall.wins} wins, {overall.losses} losses
            {overall.last_played && (
              <>
                , newest <TimeAgo at={overall.last_played} />
              </>
            )}
            . These are the games Riftline holds, not their whole season.
          </>
        }
      >
        <span
          tabIndex={0}
          className="tnum whitespace-nowrap text-[11px]"
          style={{
            color:
              overall.win_rate === null
                ? 'var(--color-ink-faint)'
                : winRateColor(overall.win_rate, 0.6),
          }}
        >
          {overall.games}g{' '}
          {overall.win_rate === null ? (
            <span className="text-ink-faint">{overall.wins}-{overall.losses}</span>
          ) : (
            pct(overall.win_rate)
          )}
        </span>
      </Hint>

      {overall.avg_score !== null && (
        <Hint
          text={
            `Riftline score of ${overall.avg_score.toFixed(1)} over ${overall.scored_games} scored games` +
            (overall.score_enough ? '.' : ', which is a thin sample.')
          }
        >
          <span
            tabIndex={0}
            className="tnum whitespace-nowrap text-[11px] font-600"
            style={{
              color: overall.score_enough
                ? scoreColor(overall.avg_score)
                : 'var(--color-ink-faint)',
            }}
          >
            {overall.avg_score.toFixed(1)}
          </span>
        </Hint>
      )}

      {record.on_main_position === false && record.main_position && (
        <Hint
          text={
            `They play ${positionLabel(record.main_position)} in ${record.main_position_games} of the ` +
            `${record.positioned_games} stored games we hold for them. This game they are somewhere else.`
          }
        >
          <span tabIndex={0} className="whitespace-nowrap text-[10px] font-600 text-gold">
            off role
          </span>
        </Hint>
      )}

      {!dense &&
        (champ ? (
          <Hint
            text={
              `${champ.games} stored ${champ.games === 1 ? 'game' : 'games'} on ${championName}: ` +
              `${champ.wins} wins, ${champ.losses} losses.`
            }
          >
            <span tabIndex={0} className="tnum whitespace-nowrap text-[11px] text-ink-faint">
              {champ.games}g on {championName.length > 9 ? 'this' : championName}
            </span>
          </Hint>
        ) : (
          <Hint
            text={`We hold no game of theirs on ${championName}. Mastery says whether they have played it at all.`}
          >
            <span tabIndex={0} className="whitespace-nowrap text-[11px] text-ink-faint">
              none on {championName.length > 9 ? 'this' : championName}
            </span>
          </Hint>
        ))}
    </>
  )
}
