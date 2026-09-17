import type { ChampionDetail, FacetEntry } from '../../lib/api'
import { EmptyState } from '../StateViews'
import { compact, pct } from '../../lib/format'

interface Props {
  laning: ChampionDetail['laning']
  skills: ChampionDetail['skills']
  championName: string
}

const ABILITY = ['Q', 'W', 'E', 'R']

/**
 * How the laning phase goes, and how the champion is levelled.
 *
 * Both come from match timelines, which are fetched separately from matches, so
 * a champion can have hundreds of games and no laning data at all. The header
 * states the sample outright rather than letting an average imply the full
 * game count.
 */
export default function LaningPanel({ laning, skills, championName }: Props) {
  if (laning.games === 0 && skills.priority.length === 0) {
    return (
      <EmptyState
        title="No timeline data yet"
        body="Laning scores and skill order come from match timelines, which are fetched separately. Run python -m scripts.ingest timelines, then aggregate."
      />
    )
  }

  const score = laning.avg_score
  return (
    <div className="space-y-5">
      {score !== null && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Laning phase</h3>
            <p className="text-xs text-ink-faint">
              Measured at 14 minutes, over {compact(laning.games)} game
              {laning.games === 1 ? '' : 's'} with a timeline.
            </p>
          </div>

          <div className="rounded-sm border border-line bg-panel px-4 py-3.5">
            {/* The share bar is the number: 52:48 is legible at a glance in a
                way "0.52" is not. */}
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-display font-700 text-ink">{championName}</span>
              <span className="tnum font-display text-lg font-800 text-gold-bright">
                {Math.round(score * 100)}
                <span className="mx-1 text-ink-faint">:</span>
                <span className="text-ink-dim">{100 - Math.round(score * 100)}</span>
              </span>
              <span className="text-ink-faint">opponent</span>
            </div>

            <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-raised">
              <div
                className="bg-win"
                style={{ width: `${score * 100}%` }}
                aria-label={`${championName} takes ${pct(score)} of the lane`}
              />
              <div className="flex-1 bg-loss/60" aria-hidden />
            </div>

            {/* Stacked label over value, matching the average cells above the
                tabs: at this width a justified pair drifts too far apart to
                read as one thing. */}
            <dl className="mt-3.5 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Diff label="Gold at 14" value={laning.avg_gold_diff} />
              <Diff label="CS at 14" value={laning.avg_cs_diff} digits={1} />
              <div>
                <dt className="text-xs text-ink-faint">Sample</dt>
                <dd className="tnum mt-0.5 text-sm font-600 text-ink">
                  {compact(laning.games)} games
                </dd>
              </div>
            </dl>
          </div>
        </section>
      )}

      {skills.priority.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Skill priority</h3>
            <p className="text-xs text-ink-faint">
              Which abilities get maxed, and in what order. The ultimate is on a
              fixed schedule, so it is not a choice and is left out.
            </p>
          </div>
          <div className="border-t border-line-soft">
            {skills.priority.map((entry) => (
              <SkillRow key={entry.ids.join()} entry={entry} arrows />
            ))}
          </div>
        </section>
      )}

      {skills.order.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h3 className="display text-base font-600 text-ink">Level-up order</h3>
            <p className="text-xs text-ink-faint">The first fifteen points, in sequence.</p>
          </div>
          <div className="border-t border-line-soft">
            {skills.order.map((entry) => (
              <SkillRow key={entry.ids.join()} entry={entry} />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}

function Diff({
  label,
  value,
  digits = 0,
}: {
  label: string
  value: number | null
  digits?: number
}) {
  if (value === null) return null
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd
        className="tnum mt-0.5 text-sm font-600"
        style={{ color: value >= 0 ? 'var(--color-win)' : 'var(--color-loss)' }}
      >
        {value >= 0 ? '+' : ''}
        {value.toFixed(digits)}
      </dd>
    </div>
  )
}

function SkillRow({ entry, arrows }: { entry: FacetEntry; arrows?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-line-soft px-2 py-2 transition-colors hover:bg-raised/30">
      <div className="flex flex-wrap items-center gap-1">
        {entry.ids.map((slot, i) => (
          <span key={i} className="flex items-center gap-1">
            {arrows && i > 0 && <span className="text-xs text-ink-faint">&rsaquo;</span>}
            <span
              className="grid size-6 place-items-center rounded-sm bg-raised font-display text-xs font-700 text-ink"
              title={`Ability ${ABILITY[slot - 1] ?? slot}`}
            >
              {ABILITY[slot - 1] ?? slot}
            </span>
          </span>
        ))}
      </div>
      <div className="ml-auto shrink-0 text-right">
        <p
          className="tnum text-sm font-600"
          style={{
            color:
              entry.win_rate >= 0.55
                ? 'var(--color-gold-bright)'
                : entry.win_rate >= 0.5
                  ? 'var(--color-win)'
                  : 'var(--color-ink-dim)',
          }}
        >
          {pct(entry.win_rate, 1)}
        </p>
        <p className="tnum text-xs text-ink-faint">
          {compact(entry.games)} games, {pct(entry.pick_rate)}
        </p>
      </div>
    </div>
  )
}
