import Hint from '../Hint'
import type { StoryMoment } from '../../lib/api'
import { clock, points } from './lanes'

/**
 * The sequences that moved the curve most, biggest first, numbered to match the
 * markers on the curve. A swing is read from the viewer's side: "+22 points"
 * is their team's chance going up.
 */
export default function Moments({ moments, team }: { moments: StoryMoment[]; team: number }) {
  if (moments.length === 0) return null
  return (
    <ol className="space-y-2">
      {moments.map((m, i) => {
        const swing = team === 100 ? m.swing : -m.swing
        return (
          <li key={m.start_ms} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-baseline gap-x-2">
            <span
              className="display grid size-5 place-items-center rounded-full bg-deep text-[11px] font-700 text-gold-bright ring-1 ring-gold"
              aria-hidden
            >
              {i + 1}
            </span>
            <span className="text-sm leading-snug text-ink">
              <span className="tnum mr-1.5 text-ink-faint">{clock(m.start_ms)}</span>
              {m.text}
            </span>
            <Hint text="Points of win chance for this side, from just before the sequence to a minute after">
              <span
                tabIndex={0}
                className="tnum text-sm font-600"
                style={{ color: swing >= 0 ? 'var(--color-win)' : 'var(--color-loss)' }}
              >
                {points(swing)}
              </span>
            </Hint>
          </li>
        )
      })}
    </ol>
  )
}
