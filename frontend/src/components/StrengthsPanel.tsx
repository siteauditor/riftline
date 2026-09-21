import { useState } from 'react'

import PositionIcon from './PositionIcon'
import type { RoleScoreProfile } from '../lib/api'
import { positionLabel, scoreColor } from '../lib/format'

/**
 * What the Riftline score says about this player, one role at a time.
 *
 * Every scored game already carries six percentiles against the same queue and
 * role. Averaged over a role they say where this player's games usually land:
 * the question other sites answer with an "analyse my games" button, answered
 * here from the numbers that are already on the page.
 *
 * A role needs `min_scored` scored games before it gets a breakdown. Below
 * that one game moves an average by ten points, which describes the last game
 * rather than the player, so the panel says how many there are and stops.
 */
export default function StrengthsPanel({ profiles }: { profiles: RoleScoreProfile[] }) {
  const ready = profiles.filter((p) => p.enough)
  const [picked, setPicked] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  if (profiles.length === 0) return null

  if (ready.length === 0) {
    const most = profiles[0]
    return (
      <p className="accent-edge bg-panel/50 py-2.5 pl-4 pr-3 text-sm text-ink-dim">
        A breakdown of their play needs {most.min_scored} scored games in one role.{' '}
        <span className="tnum text-ink">{most.scored_games}</span> so far as{' '}
        {positionLabel(most.position)}.
      </p>
    )
  }

  const role = ready.find((p) => p.position === picked) ?? ready[0]
  const strongest = role.components[0]
  const weakest = role.components[role.components.length - 1]

  return (
    <section className="frame">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">
          How they play {positionLabel(role.position)}
        </h2>
        {ready.length > 1 && (
          <div className="flex gap-1" role="group" aria-label="Role">
            {ready.map((p) => (
              <button
                key={p.position}
                type="button"
                onClick={() => setPicked(p.position)}
                aria-pressed={p.position === role.position}
                title={`${positionLabel(p.position)}, ${p.scored_games} scored games`}
                className={`flex items-center gap-1 rounded-sm px-2 py-1 text-xs font-600 transition-colors ${
                  p.position === role.position
                    ? 'bg-raised text-gold-bright'
                    : 'text-ink-dim hover:text-ink'
                }`}
              >
                <PositionIcon position={p.position} className="size-3.5" />
                {positionLabel(p.position)}
              </button>
            ))}
          </div>
        )}
      </header>

      {/*
        On a phone this collapses to the score and one sentence, with the rest
        behind "Show all six": it sits above the match list, and a full panel
        there pushed the first game past the first screen.
      */}
      <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-4 px-4 py-3 sm:gap-x-8 sm:py-4">
        <div>
          <p>
            <span
              className="tnum display block text-4xl font-700 leading-none sm:text-5xl"
              style={{ color: scoreColor(role.avg_score) }}
            >
              {role.avg_score.toFixed(1)}
            </span>
            <span className="mt-1 block text-xs text-ink-faint">
              average, {role.scored_games} games
            </span>
          </p>
          <dl
            className={`${expanded ? 'grid' : 'hidden'} mt-3 grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs sm:grid`}
          >
            <dt className="text-ink-faint">Placement</dt>
            <dd className="tnum text-ink">{role.avg_placement.toFixed(1)} of 10</dd>
            <dt className="text-ink-faint">MVP</dt>
            <dd className="tnum text-ink">{role.mvp}</dd>
            <dt className="text-ink-faint">ACE</dt>
            <dd className="tnum text-ink">{role.ace}</dd>
          </dl>
        </div>

        <div className="min-w-0">
          <p className="text-sm text-ink">
            Strongest at {strongest.label.toLowerCase()}, weakest at{' '}
            {weakest.label.toLowerCase()}.
          </p>
          <ul className={`${expanded ? '' : 'hidden'} mt-3 space-y-2 sm:block`}>
            {role.components.map((c) => (
              <ComponentBar key={c.id} component={c} />
            ))}
          </ul>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="mt-2 text-xs text-ink-dim underline decoration-line underline-offset-2 hover:text-ink sm:hidden"
          >
            {expanded ? 'Show less' : 'Show all six'}
          </button>
        </div>
      </div>

      <p
        className={`${expanded ? '' : 'hidden'} border-t border-line-soft px-4 py-2 text-xs leading-relaxed text-ink-faint sm:block`}
      >
        Each bar is where a typical game of theirs lands among
        {role.sample ? ` ${role.sample.toLocaleString()} ` : ' the '}
        {positionLabel(role.position).toLowerCase()} games Riftline holds, with 50 in the
        middle.
      </p>
    </section>
  )
}

function ComponentBar({ component }: { component: RoleScoreProfile['components'][number] }) {
  const value = Math.round(component.avg_percentile * 100)
  // Gold for a real strength, red for a real weakness, grey for the middle.
  // The middle band is wide on purpose: 55 against 45 is noise at this depth.
  const colour =
    value >= 65
      ? 'var(--color-gold-bright)'
      : value <= 35
        ? 'var(--color-loss)'
        : 'var(--color-ink-dim)'
  return (
    <li
      title={component.measures}
      className="grid grid-cols-[6.5rem_1fr_2rem] items-center gap-3 sm:grid-cols-[9rem_1fr_2rem]"
    >
      <span className="truncate text-xs text-ink-dim">{component.label}</span>
      <span className="relative h-1.5 rounded-full bg-raised" aria-hidden>
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${value}%`, backgroundColor: colour }}
        />
        {/* The middle of the corpus, so above and below read at a glance. */}
        <span className="absolute inset-y-[-3px] left-1/2 w-px bg-ink-faint/60" />
      </span>
      <span className="tnum text-right text-xs font-600" style={{ color: colour }}>
        {value}
      </span>
    </li>
  )
}
