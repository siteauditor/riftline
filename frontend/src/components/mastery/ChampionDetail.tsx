import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'

import type { PoolChampion } from './pool'
import { levelStep } from './scale'
import { compact, pct, scoreColor, timeAgo, winRateColor } from '../../lib/format'

/**
 * One champion, opened from a tile.
 *
 * **Not a dialog.** The grid behind it stays live and useful: comparing two
 * champions means clicking a second tile, not closing anything first. It used
 * to claim `role="dialog"` and honour none of the obligations that come with
 * it, so it is now a labelled region that owes no backdrop and no focus trap.
 * It does owe Escape and a way back to the tile, and it has both.
 *
 * Portalled, because `ArtHeader` above it already sets `isolate` and
 * `overflow-hidden`: the day any ancestor gains a transform, a fixed child
 * would silently start positioning against that ancestor instead of the
 * viewport.
 */
export default function ChampionDetail({
  champion,
  base,
  onClose,
}: {
  champion: PoolChampion
  /** The player's profile path, for the link to their games. */
  base: string
  onClose: () => void
}) {
  const panel = useRef<HTMLDivElement>(null)
  const step = levelStep(champion.level)
  const entry = champion.entry
  const record = champion.record

  useEffect(() => {
    panel.current?.focus()
  }, [champion.id])

  const close = useCallback(() => {
    // By id rather than a stored ref: the name filter can unmount the tile
    // while this is open, and a ref would then point at a detached node.
    const tile = document.getElementById(`mastery-tile-${champion.id}`)
    onClose()
    tile?.focus()
  }, [champion.id, onClose])

  // Escape goes through the same path as the button, so both put focus back on
  // the tile. Closing with the keyboard and landing on `document.body` was the
  // first thing this panel got wrong.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [close])

  return createPortal(
    <div
      ref={panel}
      tabIndex={-1}
      role="region"
      aria-label={`${champion.name} mastery`}
      className="fixed inset-x-0 bottom-0 z-50 border-t border-line bg-panel px-4 py-3 shadow-[0_-8px_24px_rgba(0,0,0,0.4)]"
    >
      <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex min-w-[12rem] items-center gap-3">
          <span
            className="size-12 shrink-0 overflow-hidden"
            style={{ boxShadow: `inset 0 0 0 2px ${step.color}` }}
          >
            {champion.iconUrl ? (
              <img src={champion.iconUrl} alt="" className="size-full object-cover" loading="lazy" decoding="async" />
            ) : (
              <span className="grid size-full place-items-center bg-raised text-ink-faint">?</span>
            )}
          </span>
          <div className="min-w-0">
            <p className="display text-base font-700 text-ink">{champion.name}</p>
            <p className="text-xs text-ink-faint">
              {champion.tags.join(', ') || 'Class unknown'}
            </p>
          </div>
        </div>

        {entry && entry.points > 0 ? (
          <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
            <Pair label="Level" value={String(entry.level)} />
            <Pair label="Points" value={compact(entry.points)} />
            <Pair label="Share of their points" value={pct(champion.share, 1)} />
            {entry.points_until_next_level > 0 && (
              <Pair label="To the next level" value={compact(entry.points_until_next_level)} />
            )}
            {entry.last_play_time && (
              <Pair label="Last played" value={timeAgo(entry.last_play_time)} />
            )}
            {/* Riot's own season figures, drawn only where Riot filled them:
                measured on one account, 23 of 166 champions carry a milestone
                and 35 carry grades. */}
            {entry.season_milestone != null && entry.season_milestone > 0 && (
              <Pair label="Season milestone" value={String(entry.season_milestone)} />
            )}
            {entry.tokens_earned > 0 && (
              <Pair
                label="Tokens"
                value={String(entry.tokens_earned)}
                title="The number Riot reports toward this champion's next level."
              />
            )}
            {entry.milestone_grades && entry.milestone_grades.length > 0 && (
              <div>
                <dt className="text-xs text-ink-faint">Grades this season</dt>
                <dd className="mt-0.5 flex flex-wrap gap-1">
                  {entry.milestone_grades.map((grade, i) => (
                    <span
                      key={`${grade}-${i}`}
                      className="bg-raised px-1.5 text-[11px] font-600 text-ink-dim"
                    >
                      {grade}
                    </span>
                  ))}
                </dd>
              </div>
            )}
          </dl>
        ) : (
          <p className="text-sm text-ink-faint">Never played</p>
        )}

        {/* Our own games, only where we hold some. Measured coverage: 10 of 166
            champions on one account, but 5 of the 7 in its core. */}
        {record && (
          <dl className="flex flex-wrap items-center gap-x-6 gap-y-2 border-l border-line pl-6 text-sm">
            <Pair label="Stored games" value={String(record.games)} />
            <Pair
              label="Win rate"
              value={pct(record.win_rate)}
              color={winRateColor(record.win_rate, 0.6)}
            />
            {record.avg_score !== null && (
              <Pair
                label="Riftline score"
                value={record.avg_score.toFixed(1)}
                color={scoreColor(record.avg_score)}
                title={`Over ${record.scored_games} scored games.`}
              />
            )}
          </dl>
        )}

        <div className="ml-auto flex items-center gap-2 text-sm">
          {record && (
            <Link
              to={`${base}/champions#champion-${champion.id}`}
              className="text-ink-dim underline decoration-line underline-offset-2 hover:text-gold-bright"
            >
              Their games
            </Link>
          )}
          {champion.known && (
            <Link
              to={`/champions/${champion.slug ?? champion.id}`}
              className="text-ink-dim underline decoration-line underline-offset-2 hover:text-gold-bright"
            >
              Champion page
            </Link>
          )}
          <button
            type="button"
            onClick={close}
            className="control px-2.5 py-1 text-sm text-ink-dim hover:text-gold-bright"
          >
            Close
          </button>
        </div>
      </div>

      {!champion.known && (
        <p className="mx-auto mt-2 max-w-[1280px] text-xs text-ink-faint">
          Riot sent this champion id. Our champion list does not have it yet, so
          there is no picture and no champion page.
        </p>
      )}
    </div>,
    document.body,
  )
}

function Pair({
  label,
  value,
  color,
  title,
}: {
  label: string
  value: string
  color?: string
  title?: string
}) {
  return (
    <div title={title}>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="tnum font-600" style={{ color: color ?? 'var(--color-ink)' }}>
        {value}
      </dd>
    </div>
  )
}
