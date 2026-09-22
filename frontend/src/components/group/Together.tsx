import { Link } from 'react-router-dom'

import type { GroupMember, GroupTogether } from '../../lib/api'
import { pct, timeAgo } from '../../lib/format'

/**
 * Stored games where two or more of the group were on the same side. Opponents
 * are left out: two members on opposite teams were not playing together.
 */
export default function Together({
  together,
  members,
}: {
  together: GroupTogether
  members: GroupMember[]
}) {
  const byPuuid = new Map(members.map((m) => [m.puuid, m]))
  const name = (puuid: string) => byPuuid.get(puuid)?.game_name ?? byPuuid.get(puuid)?.riot_id ?? 'Someone'

  if (members.length < 2) return null

  return (
    <section aria-labelledby="together-heading" className="space-y-3">
      <header>
        <h2 id="together-heading" className="display text-xl font-700 text-ink">
          Played together
        </h2>
        <p className="mt-0.5 text-sm text-ink-dim">
          {together.games === 0
            ? 'No stored game has two of this group on the same team yet.'
            : `${together.games.toLocaleString('en-US')} stored ${
                together.games === 1 ? 'game' : 'games'
              } with two or more of the group on one team, ${together.wins} won (${pct(
                together.wins / together.games,
              )}).`}
        </p>
      </header>

      {together.games > 0 && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div>
            <h3 className="eyebrow mb-1.5">Pairs</h3>
            {together.pairs.length === 0 ? (
              <p className="text-xs text-ink-faint">
                No two players have {together.min_pair_games} games together yet, the fewest a
                pair is shown with.
              </p>
            ) : (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-xs text-ink-faint">
                    <th className="py-1.5 text-left font-500">Pair</th>
                    <th className="py-1.5 text-right font-500">Games</th>
                    <th className="py-1.5 pl-3 text-right font-500">Won</th>
                  </tr>
                </thead>
                <tbody>
                  {together.pairs.map((p) => (
                    <tr key={`${p.a}-${p.b}`} className="border-b border-line-soft">
                      <td className="py-1.5 pr-2 text-ink">
                        <span className="block break-words">{name(p.a)}</span>
                        <span className="block break-words">
                          <span className="text-ink-faint">and </span>
                          {name(p.b)}
                        </span>
                      </td>
                      <td className="tnum py-1.5 text-right text-ink-dim">{p.games}</td>
                      <td
                        className={`tnum py-1.5 pl-3 text-right font-600 ${
                          p.win_rate >= 0.5 ? 'text-ink' : 'text-ink-dim'
                        }`}
                      >
                        {pct(p.win_rate)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <h3 className="eyebrow mb-1.5">Newest</h3>
            <ul className="divide-y divide-line-soft border-y border-line-soft">
              {together.recent.map((g) => (
                <li key={g.match_id}>
                  <Link
                    to={`/match/${encodeURIComponent(g.match_id)}?player=${encodeURIComponent(g.players[0].puuid)}`}
                    className="lift flex flex-wrap items-center gap-x-3 gap-y-1.5 px-1 py-2 text-xs"
                  >
                    <span
                      className={`w-9 shrink-0 font-700 ${g.win ? 'text-win' : 'text-loss'}`}
                    >
                      {g.win ? 'Won' : 'Lost'}
                    </span>
                    <span className="w-28 shrink-0 truncate text-ink-dim">
                      {g.queue_name}
                      <span className="block text-ink-faint">{timeAgo(g.game_creation)}</span>
                    </span>
                    <span className="flex min-w-0 flex-1 flex-wrap gap-x-3 gap-y-1">
                      {g.players.map((p) => (
                        <span key={p.puuid} className="flex min-w-0 items-center gap-1.5">
                          {p.champion.icon_url && (
                            <img src={p.champion.icon_url} alt="" className="size-5 ring-1 ring-line" />
                          )}
                          <span className="truncate text-ink">{name(p.puuid)}</span>
                          <span className="tnum text-ink-faint">
                            {p.kills}/{p.deaths}/{p.assists}
                          </span>
                        </span>
                      ))}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  )
}
