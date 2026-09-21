import { Link } from 'react-router-dom'

import RankBadge from '../RankBadge'
import { Loadout, MasteryChip, SkinArt } from './PlayerBits'
import PlayerRecordChips from './PlayerRecordChips'
import type { LiveGame, LiveParticipant } from '../../lib/api'
import { pct } from '../../lib/format'

export default function TeamView({ game, platform, you }: { game: LiveGame; platform: string; you: string }) {
  // Grouped by whatever team ids the mode actually uses, not a hardcoded
  // 100/200. Arena runs eight teams of two, and assuming two sides renders two
  // empty columns and dumps all sixteen players into a third. MatchRow already
  // learned this lesson; this is the same rule.
  const byTeam = new Map<number, LiveParticipant[]>()
  for (const p of game.participants) {
    const bucket = byTeam.get(p.team_id)
    if (bucket) bucket.push(p)
    else byTeam.set(p.team_id, [p])
  }
  const teams = [...byTeam.entries()].sort(([a], [b]) => a - b)
  const twoSided = teams.length === 2
  // Arena reports all sixteen or eighteen players under one team id: its real
  // pairs live in a field spectator-v5 does not carry. One group is therefore
  // one group, and calling it "Team 1" would invent a division we cannot see.
  const oneGroup = teams.length === 1

  return (
    <div className={`grid gap-4 ${oneGroup ? '' : 'lg:grid-cols-2'}`}>
      {teams.map(([teamId, team], i) => (
        <section key={teamId}>
          <h3
            className="mb-1 border-b border-line pb-1.5 display text-base font-600"
            style={{
              color: twoSided
                ? i === 0
                  ? 'var(--color-win)'
                  : 'var(--color-loss)'
                : 'var(--color-ink)',
            }}
          >
            {twoSided
              ? i === 0
                ? 'Blue side'
                : 'Red side'
              : oneGroup
                ? `All ${team.length} players`
                : `Team ${i + 1}`}
          </h3>
          <ul className={oneGroup ? 'sm:grid sm:grid-cols-2 sm:gap-x-4' : ''}>
            {team.map((p, j) => (
              <PlayerRow
                key={p.puuid ?? `${teamId}-${j}`}
                p={p}
                platform={platform}
                isYou={Boolean(p.puuid) && p.puuid === you}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}

function PlayerRow({
  p,
  platform,
  isYou,
}: {
  p: LiveParticipant
  platform: string
  isYou: boolean
}) {
  const [name, tag] = (p.riot_id ?? '').split('#')
  const linkable = Boolean(p.riot_id && name && tag)

  return (
    <li
      className={`flex items-center gap-2.5 border-b border-l-2 border-line-soft px-2 py-2 lift ${
        isYou ? 'border-l-gold bg-gold/[0.06]' : 'border-l-transparent'
      }`}
    >
      <span className="size-9 shrink-0 overflow-hidden rounded-sm bg-raised">
        <SkinArt p={p} className="size-full object-cover" />
      </span>

      <Loadout p={p} />

      <span className="min-w-0 flex-1 truncate text-sm">
        {linkable ? (
          <Link
            to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
            className="display text-[15px] font-600 text-ink transition-colors hover:text-gold-bright"
          >
            {name}
          </Link>
        ) : (
          // Never the champion name Riot puts in `riotId` for a hidden player:
          // it would read as a person and link to a profile that does not exist.
          <span className="display text-[15px] font-600 text-ink-faint">
            {p.champion.name}
          </span>
        )}
      </span>

      {/* Dense here: one line per player, so the champion specific record
          stays on the lane cards where there is room for it. */}
      <span className="hidden shrink-0 items-center gap-2 sm:flex">
        <PlayerRecordChips p={p} championName={p.champion.name} dense />
      </span>

      <MasteryChip p={p} />
      <RankBadge
        state={p.state}
        tier={p.rank?.tier}
        division={p.rank?.division}
        leaguePoints={p.rank?.league_points}
      />
      {p.rank && p.rank.games > 0 && (
        <span
          title={`${p.rank.wins}W ${p.rank.losses}L this season, ${pct(p.rank.win_rate, 1)} win rate`}
          className="tnum hidden w-16 shrink-0 text-right text-xs text-ink-faint sm:block"
        >
          {pct(p.rank.win_rate)} WR
        </span>
      )}
    </li>
  )
}
