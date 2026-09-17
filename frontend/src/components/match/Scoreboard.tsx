import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import PositionIcon from '../PositionIcon'
import { ErrorView, Spinner } from '../StateViews'
import {
  api,
  type ScoreModel,
  type ScoreboardPlayer,
  type TeamObjectives,
} from '../../lib/api'
import { compact, ordinal, pct, positionLabel, scoreColor } from '../../lib/format'

/**
 * The expanded match: every player's game, not just the searched player's.
 *
 * Fetched when a row is opened rather than shipped with the history page. Ten
 * players times twenty matches of items, wards and damage is a payload nobody
 * asked for on every scroll, and most rows are never opened.
 *
 * The bars are comparative, not absolute. A damage number means nothing on its
 * own: 30k is a carry performance in a fifteen-minute game and a quiet one in a
 * forty-minute game, so every bar is drawn against the highest figure in this
 * lobby and the number stays beside it for anyone who wants the absolute.
 */
export default function Scoreboard({
  matchId,
  subjectPuuid,
  platform,
}: {
  matchId: string
  subjectPuuid: string
  platform: string
}) {
  const query = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => api.matchDetail(matchId),
    // A finished match never changes, so this is the one query in the app that
    // can be cached for the session and never refetched.
    staleTime: Infinity,
    retry: false,
  })

  if (query.isLoading) {
    return (
      <div className="px-3 py-4">
        <Spinner label="Loading the scoreboard" />
      </div>
    )
  }
  if (query.isError || !query.data) {
    return (
      <div className="px-3 py-4">
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const detail = query.data
  const everyone = detail.teams.flat()
  // Only a Rift game has sides. Arena puts two groups of nine on team ids 100
  // and 200, which is Riot's bookkeeping, not blue and red.
  const hasSides = everyone.every((p) => p.position)
  const peak = {
    damage: Math.max(1, ...everyone.map((p) => p.damage_to_champions)),
    taken: Math.max(1, ...everyone.map((p) => p.damage_taken)),
  }

  return (
    <div className="border-t border-line-soft bg-deep/40 px-3 py-4">
      {detail.score_withheld && (
        <p className="mb-4 border-l-2 border-gold/50 py-1 pl-3 text-xs leading-relaxed text-ink-dim">
          <span className="text-ink">No Riftline score for this game.</span>{' '}
          {detail.score_withheld}
        </p>
      )}

      <div className="grid gap-5">
        {detail.teams.map((team, i) => {
          const objectives = detail.objectives.find(
            (o) => o.team_id === team[0]?.team_id,
          )
          return (
            <section key={team[0]?.team_id ?? i} className="min-w-0">
              <header className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 border-b border-line pb-1.5">
                <h3
                  className="display text-base font-600"
                  style={{
                    color: team[0]?.win ? 'var(--color-win)' : 'var(--color-loss)',
                  }}
                >
                  {team[0]?.win ? 'Victory' : 'Defeat'}
                  {hasSides && (
                    <span className="ml-2 text-sm font-500 text-ink-faint">
                      {i === 0 ? 'Blue side' : 'Red side'}
                    </span>
                  )}
                </h3>
                {objectives && <Objectives objectives={objectives} />}
              </header>

              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] border-collapse text-xs">
                  <thead>
                    <tr className="text-[11px] text-ink-faint">
                      <th className="py-1 text-left font-500">Player</th>
                      <th
                        className="py-1 pl-2 text-right font-500"
                        title="The Riftline score, and where it placed in this lobby"
                      >
                        Score
                      </th>
                      <th className="py-1 pl-2 text-right font-500">KDA</th>
                      <th className="py-1 pl-2 text-right font-500">Damage</th>
                      <th className="py-1 pl-2 text-right font-500">Taken</th>
                      <th className="py-1 pl-2 text-right font-500">CS</th>
                      <th className="py-1 pl-2 text-right font-500">Vis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...team]
                      .sort((a, b) => (a.placement ?? 99) - (b.placement ?? 99))
                      .map((p) => (
                        <Row
                          key={p.puuid}
                          player={p}
                          platform={platform}
                          peak={peak}
                          isSubject={p.puuid === subjectPuuid}
                        />
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          )
        })}
      </div>

      {detail.model && <ModelNote model={detail.model} teams={detail.teams} />}
    </div>
  )
}

function Objectives({ objectives }: { objectives: TeamObjectives }) {
  // Omitted rather than shown as zeroes when Riot's team objects describe
  // something other than these sides, which is what happens in Arena. Kills and
  // gold are always summed from the players above, so they stay.
  const counts: [string, number, string][] = objectives.objectives_known
    ? [
        ['B', objectives.baron, 'Barons'],
        ['D', objectives.dragon, 'Dragons'],
        ['H', objectives.herald, 'Heralds'],
        ['T', objectives.tower, 'Towers'],
        ['I', objectives.inhibitor, 'Inhibitors'],
      ]
    : []
  return (
    <p className="tnum flex flex-wrap items-baseline gap-x-2.5 text-[11px] text-ink-faint">
      <span title="Kills by this side, summed from its own players">
        <span className="text-ink-dim">{objectives.kills}</span> kills
      </span>{' '}
      <span title="Gold earned by this side">
        <span className="text-ink-dim">{compact(objectives.gold)}</span> gold
      </span>{' '}
      {counts.map(([letter, n, label]) => (
        <span key={letter} title={`${label} taken`} className={n ? '' : 'opacity-50'}>
          <span className="text-ink-dim">{letter}</span>
          {n}{' '}
        </span>
      ))}
    </p>
  )
}

function Row({
  player,
  platform,
  peak,
  isSubject,
}: {
  player: ScoreboardPlayer
  platform: string
  peak: { damage: number; taken: number }
  isSubject: boolean
}) {
  const [name, tag] = (player.riot_id ?? '').split('#')
  return (
    <tr
      className={`border-t border-line-soft ${
        isSubject ? 'bg-gold/[0.06]' : 'hover:bg-raised/30'
      }`}
    >
      <td className="py-1.5 pr-2">
        <div className="flex items-center gap-1.5">
          <span className="relative shrink-0">
            {player.champion.icon_url && (
              <img
                src={player.champion.icon_url}
                alt={player.champion.name}
                title={player.champion.name}
                loading="lazy"
                className="size-7 rounded-sm"
              />
            )}
            <span className="tnum absolute -bottom-1 -right-1 rounded-full bg-deep px-1 text-[9px] font-600 text-ink-dim ring-1 ring-line">
              {player.champ_level}
            </span>
          </span>
          <PositionIcon
            position={player.position}
            className="size-3.5 shrink-0 text-ink-faint"
          />
          {name && tag ? (
            <Link
              to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
              className="min-w-0 truncate text-ink-dim transition-colors hover:text-gold-bright"
            >
              {name}
            </Link>
          ) : (
            <span className="min-w-0 truncate text-ink-faint">
              {player.champion.name}
            </span>
          )}
          {player.badges.slice(0, 2).map((badge) => (
            <span
              key={badge.id}
              title={badge.detail}
              className="shrink-0 rounded-sm bg-gold/15 px-1 text-[10px] font-600 text-gold-bright"
            >
              {badge.label}
            </span>
          ))}
        </div>
      </td>

      <td className="py-1.5 pl-2 text-right">
        {player.score === null ? (
          <span className="text-ink-faint">-</span>
        ) : (
          <span className="tnum display text-[15px] font-700" style={{ color: scoreColor(player.score) }}>
            {player.score.toFixed(1)}
            <span
              className="ml-1 text-[10px] font-500 text-ink-faint"
              title={`${ordinal(player.placement ?? 0)} of ten in this lobby`}
            >
              #{player.placement}
            </span>
          </span>
        )}
      </td>

      <td className="tnum py-1.5 pl-2 text-right text-ink-dim">
        {player.kills}/<span className="text-loss">{player.deaths}</span>/
        {player.assists}
        <span
          className="ml-1 text-[10px] text-ink-faint"
          title="Kill participation"
        >
          {pct(player.kill_participation)}
        </span>
      </td>

      <Bar
        value={player.damage_to_champions}
        peak={peak.damage}
        tone="var(--color-gold)"
      />
      <Bar
        value={player.damage_taken}
        peak={peak.taken}
        tone="var(--color-ink-faint)"
      />

      <td className="tnum py-1.5 pl-2 text-right text-ink-dim">
        {player.cs}
        <span className="ml-1 text-[10px] text-ink-faint">
          {player.cs_per_min.toFixed(1)}
        </span>
      </td>
      <td
        className="tnum py-1.5 pl-2 text-right text-ink-dim"
        title={
          player.wards_placed === null
            ? 'Vision score'
            : `${player.wards_placed} wards placed, ${player.wards_killed} killed, ${player.control_wards} control`
        }
      >
        {player.vision_score}
      </td>
    </tr>
  )
}

/** A figure and its share of the lobby's highest, which is what makes it read. */
function Bar({
  value,
  peak,
  tone,
}: {
  value: number
  peak: number
  tone: string
}) {
  return (
    <td className="py-1.5 pl-2 text-right align-middle">
      <span className="tnum text-ink-dim">{compact(value)}</span>
      <span
        aria-hidden
        className="mt-0.5 block h-1 w-full overflow-hidden rounded-full bg-raised"
      >
        <span
          className="block h-full"
          style={{ width: `${(value / peak) * 100}%`, background: tone }}
        />
      </span>
    </td>
  )
}

/**
 * The model, openly.
 *
 * itero publishes its draft model and it is the most trustworthy thing on their
 * site; op.gg's OP Score is a black box. A rating nobody can take apart has to
 * be taken on faith, which is the opposite of the point.
 */
function ModelNote({
  model,
  teams,
}: {
  model: ScoreModel
  teams: ScoreboardPlayer[][]
}) {
  const [open, setOpen] = useState(false)
  // The weights that actually applied to the player whose history this is.
  const roles = [...new Set(teams.flat().map((p) => p.position))].filter(
    Boolean,
  ) as string[]

  return (
    <div className="mt-4 border-t border-line-soft pt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="text-[11px] text-ink-faint transition-colors hover:text-ink-dim"
      >
        How the Riftline score is measured {open ? '(hide)' : ''}
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          <p className="max-w-[80ch] text-[11px] leading-relaxed text-ink-dim">
            {model.note}
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-[460px] border-collapse text-[11px]">
              <thead>
                <tr className="text-ink-faint">
                  <th className="py-1 pr-3 text-left font-500">Component</th>
                  <th className="py-1 pr-3 text-left font-500">What it measures</th>
                  {roles.map((role) => (
                    <th key={role} className="py-1 pl-2 text-right font-500">
                      <PositionIcon
                        position={role}
                        className="ml-auto size-3.5 text-ink-faint"
                      />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {model.components.map((component) => (
                  <tr key={component.id} className="border-t border-line-soft">
                    <td className="py-1 pr-3 text-ink-dim">{component.label}</td>
                    <td className="py-1 pr-3 text-ink-faint">{component.measures}</td>
                    {roles.map((role) => (
                      <td key={role} className="tnum py-1 pl-2 text-right text-ink-dim">
                        {((model.weights[role]?.[component.id] ?? 0) * 100).toFixed(0)}%
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-ink-faint">{sampleLine(model)}</p>
        </div>
      )}
    </div>
  )
}

/**
 * What the percentiles were measured against.
 *
 * The five roles usually hold the same number of games, because every ranked
 * match contributes exactly one of each, so listing them separately prints the
 * same figure five times as though it were five facts.
 */
function sampleLine(model: ScoreModel): string {
  const counts = Object.values(model.samples)
  if (counts.length === 0) return 'Measured against our stored matches.'
  const same = counts.every((n) => n === counts[0])
  if (same) {
    return `Measured against ${counts[0].toLocaleString()} games in each role in our corpus.`
  }
  const parts = Object.entries(model.samples).map(
    ([role, n]) => `${n.toLocaleString()} ${positionLabel(role).toLowerCase()}`,
  )
  return `Measured against ${parts.join(', ')} games in our corpus.`
}
