import { Link } from 'react-router-dom'

import type { ChampionPlayers } from '../../lib/api'
import Crest from '../Crest'
import { EmptyState } from '../StateViews'
import { pct, scoreColor, tierLabel, winRateColor } from '../../lib/format'
import { summonerPath } from '../../lib/profileAddress'

/**
 * Who does best on this champion, by average Riftline score.
 *
 * Over every Summoner's Rift game we hold rather than the patch chosen above:
 * who is good on a champion is not a patch question, and the slice would cost
 * a third of the sample. The record sits beside the score on purpose. A score
 * rates how someone played, not whether they won, so a 5 game, 0 win row can
 * rank above a winning one, and hiding the record would make that look like
 * a bug rather than the point.
 */
export default function PlayersPanel({ board, championName }: { board: ChampionPlayers; championName: string }) {
  if (board.players.length === 0) {
    return (
      <EmptyState
        title="Not enough players yet"
        body={
          board.qualified === 0
            ? `Nobody in the games we hold has ${board.min_games} or more games on ${championName}, with ${board.min_scored} of them scored.`
            : `${board.qualified} ${board.qualified === 1 ? 'player has' : 'players have'} ${board.min_games} or more scored games on ${championName} in the games we hold. The board appears at 3, because below that it lists whoever was crawled rather than ranking anyone.`
        }
      />
    )
  }

  return (
    // Capped: five columns across 1280px put the score a long way from the
    // name it belongs to.
    <section className="max-w-4xl">
      <div className="mb-2">
        <h3 className="display text-base font-600 text-ink">Best {championName} players</h3>
        <p className="mt-0.5 max-w-prose text-xs leading-relaxed text-ink-faint">
          Ranked by average Riftline score over every game we hold, not the patch above,
          pulled toward {championName}&apos;s average
          {board.champion_score !== null && ` of ${board.champion_score.toFixed(1)}`} by{' '}
          {board.score_strength} games, so a few good games do not top a long record. The score
          column is each player&apos;s own average. {board.qualified}{' '}
          {board.qualified === 1 ? 'player qualifies' : 'players qualify'} with {board.min_games} or
          more games, {board.min_scored} of them scored.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="w-8 py-1.5 text-left font-500">#</th>
              <th className="py-1.5 text-left font-500">Player</th>
              <th className="py-1.5 text-right font-500" aria-sort="descending">
                Score
              </th>
              <th className="py-1.5 text-right font-500">Record</th>
              <th className="py-1.5 text-right font-500">Win rate</th>
            </tr>
          </thead>
          <tbody>
            {board.players.map((p, i) => {
              const name = p.game_name ?? 'Unnamed player'
              const to =
                p.game_name && p.tag_line && p.platform
                  ? summonerPath(p.platform, p.game_name, p.tag_line)
                  : null
              return (
                <tr key={p.puuid} className="lift border-b border-line-soft">
                  <td className="tnum py-2 text-ink-faint">{i + 1}</td>
                  <td className="py-2">
                    <div className="flex min-w-0 items-center gap-2.5">
                      {/* A fixed slot, so an unranked player's name lines up
                          with the ranked ones instead of sliding left. */}
                      <span className="grid size-8 shrink-0 place-items-center">
                        <Crest tier={p.tier} division={p.division} size="line" />
                      </span>
                      <div className="min-w-0">
                        {to ? (
                          <Link
                            to={to}
                            className="display block truncate text-[15px] font-600 text-ink hover:text-gold-bright"
                          >
                            {name}
                            <span className="ml-1 text-xs font-500 text-ink-faint">#{p.tag_line}</span>
                          </Link>
                        ) : (
                          <span className="display block truncate text-[15px] font-600 text-ink">{name}</span>
                        )}
                        <span className="text-xs text-ink-faint">
                          {p.platform.toUpperCase()}
                          {p.tier && `, ${tierLabel(p.tier, p.division)}`}
                        </span>
                      </div>
                    </div>
                  </td>
                  <td className="py-2 text-right">
                    <span
                      className="tnum display text-lg font-700"
                      style={{ color: scoreColor(p.avg_score) }}
                    >
                      {p.avg_score.toFixed(1)}
                    </span>
                    {p.scored_games < p.games && (
                      <span className="block text-[11px] text-ink-faint">
                        over {p.scored_games} scored
                      </span>
                    )}
                  </td>
                  <td className="tnum py-2 text-right text-ink-dim">
                    {p.wins}W {p.games - p.wins}L
                  </td>
                  <td className="tnum py-2 text-right" style={{ color: winRateColor(p.win_rate) }}>
                    {pct(p.win_rate)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
