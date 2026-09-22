import { useState } from 'react'

import type { StoryPlayer } from '../../lib/api'
import { clock, points } from './lanes'

// Rows shown before "Show all": a carry's game can hold thirty takedowns.
const SHOWN = 8

// Summoner's Rift in game units, as Riot places events on it.
const MAP_MIN = -120
const MAP_MAX_X = 14870
const MAP_MAX_Y = 14980

/**
 * One player's deaths and takedowns, weighed.
 *
 * A death is traded when the team got a kill, an objective, a building or a
 * plate back within a minute; the rest are the deaths the team got nothing
 * for. A takedown is converted when the team took an objective or a building
 * within a minute. Each carries what it did to the team's chance to win, when
 * the model behind that is published.
 */
export default function DeathReview({
  players,
  subjectIndex,
  mapUrl,
  published,
}: {
  players: StoryPlayer[]
  subjectIndex: number | null
  mapUrl: string | null
  published: boolean
}) {
  const [chosen, setChosen] = useState<number | null>(subjectIndex)
  const [allDeaths, setAllDeaths] = useState(false)
  const [allTakedowns, setAllTakedowns] = useState(false)
  const player =
    players.find((p) => p.participant_index === chosen) ??
    players.find((p) => p.participant_index === subjectIndex) ??
    players[0]
  if (!player) return null

  const label = (p: StoryPlayer) => `${p.champion.name}${p.riot_id ? `, ${p.riot_id.split('#')[0]}` : ''}`

  return (
    <section className="min-w-0" aria-labelledby="review-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h3 id="review-heading" className="display text-base font-600 text-ink">
          Deaths and takedowns
        </h3>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-ink-faint">Player</span>
          <select
            value={player.participant_index}
            onChange={(e) => setChosen(Number(e.target.value))}
            className="control max-w-[14rem]"
          >
            {players.map((p) => (
              <option key={p.participant_index} value={p.participant_index}>
                {label(p)}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-ink-dim">
        <Fact value={`${player.deaths}`} what={player.deaths === 1 ? 'death' : 'deaths'} />
        {player.deaths > 0 && (
          <>
            , <Fact value={`${player.untraded}`} what="untraded" tone={player.untraded ? 'loss' : undefined} />
          </>
        )}
        {published && player.win_lost !== null && player.deaths > 0 && (
          <>
            , <Fact value={points(-player.win_lost)} what="points of win chance" tone="loss" />
          </>
        )}
        . <Fact value={`${player.takedowns}`} what={player.takedowns === 1 ? 'takedown' : 'takedowns'} />
        {player.takedowns > 0 && (
          <>
            , <Fact value={`${player.converted}`} what="turned into an objective" />
          </>
        )}
        {published && player.win_gained !== null && player.takedowns > 0 && (
          <>
            , <Fact value={points(player.win_gained)} what="points" tone="win" />
          </>
        )}
        .
        {player.contests > 0 && (
          <>
            {' '}
            Objective fights: <Fact value={`${player.contests_won} of ${player.contests}`} what="won" />.
          </>
        )}
      </p>

      <div className="mt-4 grid gap-5 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]">
        {mapUrl && player.death_list.length > 0 && (
          <figure>
            <div className="relative aspect-square w-full max-w-[15rem] overflow-hidden rounded-sm ring-1 ring-line">
              <img src={mapUrl} alt="" className="size-full opacity-70" loading="lazy" />
              {player.death_list.map((d) => (
                <span
                  key={d.ms}
                  className={`absolute size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ${
                    d.traded ? 'bg-transparent ring-ink' : 'ring-deep'
                  }`}
                  style={{
                    left: `${((d.x - MAP_MIN) / (MAP_MAX_X - MAP_MIN)) * 100}%`,
                    top: `${100 - ((d.y - MAP_MIN) / (MAP_MAX_Y - MAP_MIN)) * 100}%`,
                    background: d.traded ? undefined : 'var(--color-loss)',
                  }}
                  title={`${clock(d.ms)}, ${d.traded ? 'traded' : 'untraded'}`}
                />
              ))}
            </div>
            <figcaption className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-ink-faint">
              <span className="inline-flex items-center gap-1">
                <span className="size-2.5 rounded-full" style={{ background: 'var(--color-loss)' }} aria-hidden />
                Untraded death
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="size-2.5 rounded-full ring-2 ring-ink" aria-hidden />
                Traded
              </span>
            </figcaption>
          </figure>
        )}

        <div className="min-w-0 space-y-4">
          {player.death_list.length > 0 && (
            <table className="w-full border-collapse text-xs">
              <caption className="mb-1 text-left text-ink-faint">Deaths</caption>
              <thead>
                <tr className="text-ink-faint">
                  <th className="py-1 pr-2 text-left font-500">Time</th>
                  <th className="py-1 pr-2 text-left font-500">Killed by</th>
                  <th className="py-1 pr-2 text-left font-500">Got back</th>
                  {published && <th className="py-1 text-right font-500">Win chance</th>}
                </tr>
              </thead>
              <tbody>
                {(allDeaths ? player.death_list : player.death_list.slice(0, SHOWN)).map((d) => (
                  <tr key={d.ms} className="border-t border-line-soft">
                    <td className="tnum py-1 pr-2 text-ink-dim">{clock(d.ms)}</td>
                    <td className="py-1 pr-2">
                      <Who champion={d.killer?.champion ?? null} extra={d.assisters} />
                    </td>
                    <td className="py-1 pr-2" style={{ color: d.traded ? 'var(--color-ink-dim)' : 'var(--color-loss)' }}>
                      {d.traded ? 'Traded' : 'Nothing'}
                    </td>
                    {published && (
                      <td className="tnum py-1 text-right" style={{ color: 'var(--color-loss)' }}>
                        {d.cost !== null ? points(-d.cost) : ''}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {player.death_list.length > SHOWN && (
            <ShowAll open={allDeaths} count={player.death_list.length} onToggle={() => setAllDeaths((o) => !o)} />
          )}

          {player.takedown_list.length > 0 && (
            <table className="w-full border-collapse text-xs">
              <caption className="mb-1 text-left text-ink-faint">Takedowns</caption>
              <thead>
                <tr className="text-ink-faint">
                  <th className="py-1 pr-2 text-left font-500">Time</th>
                  <th className="py-1 pr-2 text-left font-500">On</th>
                  <th className="py-1 pr-2 text-left font-500">Turned into</th>
                  {published && <th className="py-1 text-right font-500">Win chance</th>}
                </tr>
              </thead>
              <tbody>
                {(allTakedowns ? player.takedown_list : player.takedown_list.slice(0, SHOWN)).map((t) => (
                  <tr key={`${t.ms}-${t.victim?.participant_index ?? 0}`} className="border-t border-line-soft">
                    <td className="tnum py-1 pr-2 text-ink-dim">{clock(t.ms)}</td>
                    <td className="py-1 pr-2">
                      <Who champion={t.victim?.champion ?? null} note={t.killed ? 'kill' : 'assist'} />
                    </td>
                    <td className="py-1 pr-2 text-ink-dim">{t.converted ? 'An objective' : ''}</td>
                    {published && (
                      <td className="tnum py-1 text-right" style={{ color: 'var(--color-win)' }}>
                        {t.gain !== null ? points(t.gain) : ''}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {player.takedown_list.length > SHOWN && (
            <ShowAll open={allTakedowns} count={player.takedown_list.length} onToggle={() => setAllTakedowns((o) => !o)} />
          )}

          {player.death_list.length === 0 && player.takedown_list.length === 0 && (
            <p className="text-sm text-ink-faint">No kills, deaths or assists this game.</p>
          )}
        </div>
      </div>
    </section>
  )
}

function ShowAll({ open, count, onToggle }: { open: boolean; count: number; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      className="-mt-2 text-xs text-ink-dim underline decoration-line underline-offset-2 transition-colors hover:text-gold-bright"
    >
      {open ? `Show the first ${SHOWN}` : `Show all ${count}`}
    </button>
  )
}

function Fact({ value, what, tone }: { value: string; what: string; tone?: 'win' | 'loss' }) {
  return (
    <span>
      <span
        className="tnum font-600"
        style={{ color: tone ? `var(--color-${tone})` : 'var(--color-ink)' }}
      >
        {value}
      </span>{' '}
      {what}
    </span>
  )
}

function Who({
  champion,
  extra = 0,
  note,
}: {
  champion: { name: string; icon_url: string | null } | null
  extra?: number
  note?: string
}) {
  if (!champion) return <span className="text-ink-faint">A turret or minions</span>
  return (
    <span className="flex items-center gap-1.5">
      {champion.icon_url && <img src={champion.icon_url} alt="" className="size-5 rounded-sm" loading="lazy" />}
      <span className="truncate text-ink-dim">{champion.name}</span>
      {extra > 0 && <span className="text-ink-faint">+{extra}</span>}
      {note && <span className="text-ink-faint">{note}</span>}
    </span>
  )
}
