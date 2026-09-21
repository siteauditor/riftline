import type { LiveParticipant } from '../../lib/api'
import { pct, positionLabel, scoreColor, timeAgo, winRateColor } from '../../lib/format'

/**
 * What this player has done, as opposed to what their champion does.
 *
 * Until this existed the lobby showed rank, mastery and the champion's win
 * rate, so nothing on the page was about the people in it. Measured 2026-09-21:
 * a median of 9 of 10 players in a stored lobby have three or more other stored
 * games, so these chips are filled in for almost everyone in a bracket we
 * crawl, and empty for anyone outside it.
 *
 * Every figure carries its sample in the title, and a record we hold too little
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
      <span
        className="text-[11px] text-ink-faint"
        title={`We hold ${p.stored_games} stored ${p.stored_games === 1 ? 'game' : 'games'} for this player, which is too few to describe how they play.`}
      >
        {p.stored_games} stored
      </span>
    )
  }

  const { overall, on_champion: champ } = record
  const last = overall.last_played ? `, newest ${timeAgo(overall.last_played)}` : ''

  return (
    <>
      <span
        className="tnum whitespace-nowrap text-[11px]"
        style={{
          color:
            overall.win_rate === null
              ? 'var(--color-ink-faint)'
              : winRateColor(overall.win_rate, 0.6),
        }}
        title={
          `${overall.games} stored games: ${overall.wins} wins, ${overall.losses} losses${last}. ` +
          'These are the games Riftline holds, not their whole season.'
        }
      >
        {overall.games}g{' '}
        {overall.win_rate === null ? (
          <span className="text-ink-faint">{overall.wins}-{overall.losses}</span>
        ) : (
          pct(overall.win_rate)
        )}
      </span>

      {overall.avg_score !== null && (
        <span
          className="tnum whitespace-nowrap text-[11px] font-600"
          style={{
            color: overall.score_enough
              ? scoreColor(overall.avg_score)
              : 'var(--color-ink-faint)',
          }}
          title={
            `Riftline score of ${overall.avg_score.toFixed(1)} over ${overall.scored_games} scored games` +
            (overall.score_enough ? '.' : ', which is a thin sample.')
          }
        >
          {overall.avg_score.toFixed(1)}
        </span>
      )}

      {record.on_main_position === false && record.main_position && (
        <span
          className="whitespace-nowrap text-[10px] font-600 text-gold"
          title={
            `They play ${positionLabel(record.main_position)} in ${record.main_position_games} of the ` +
            `${record.positioned_games} stored games we hold for them. This game they are somewhere else.`
          }
        >
          off role
        </span>
      )}

      {!dense &&
        (champ ? (
          <span
            className="tnum whitespace-nowrap text-[11px] text-ink-faint"
            title={
              `${champ.games} stored ${champ.games === 1 ? 'game' : 'games'} on ${championName}: ` +
              `${champ.wins} wins, ${champ.losses} losses.`
            }
          >
            {champ.games}g on {championName.length > 9 ? 'this' : championName}
          </span>
        ) : (
          <span
            className="whitespace-nowrap text-[11px] text-ink-faint"
            title={`We hold no game of theirs on ${championName}. Mastery says whether they have played it at all.`}
          >
            none on {championName.length > 9 ? 'this' : championName}
          </span>
        ))}
    </>
  )
}
