import { useId } from 'react'

import type { StoryMoment } from '../../lib/api'
import { clock } from './lanes'

/**
 * One team's chance to win, minute by minute.
 *
 * The plot is an SVG stretched to its box, and everything a person reads
 * (the axis, the numbered moments, the result) is HTML placed by percentage
 * on top, so the labels keep their size on a phone while the line widens on a
 * desk. The line itself is drawn with non-scaling strokes for the same reason.
 * Above the 50% line is tinted as the viewer's side winning, below as losing.
 */
export default function WinChanceCurve({
  curve,
  team,
  moments,
  durationMs,
  won,
}: {
  curve: { ms: number; blue: number; frame: boolean }[]
  /** Whose chance to draw: 100 blue, 200 red. */
  team: number
  moments: StoryMoment[]
  durationMs: number
  won: boolean | null
}) {
  const uid = useId().replace(/:/g, '')
  if (curve.length < 2) return null

  const end = Math.max(durationMs, curve[curve.length - 1].ms, 60_000)
  const mine = (blue: number) => (team === 100 ? blue : 1 - blue)
  const x = (ms: number) => (ms / end) * 100
  const y = (p: number) => (1 - p) * 100

  const line = curve
    .map((c, i) => `${i ? 'L' : 'M'}${x(c.ms).toFixed(2)},${y(mine(c.blue)).toFixed(2)}`)
    .join('')
  const area = `${line}L${x(curve[curve.length - 1].ms).toFixed(2)},50L${x(curve[0].ms).toFixed(2)},50Z`

  const at = (ms: number) => {
    let previous = curve[0]
    for (const point of curve) {
      if (point.ms >= ms) {
        if (point.ms === previous.ms) return mine(point.blue)
        const f = (ms - previous.ms) / (point.ms - previous.ms)
        return mine(previous.blue + (point.blue - previous.blue) * f)
      }
      previous = point
    }
    return mine(curve[curve.length - 1].blue)
  }

  const minutes: number[] = []
  for (let m = 5; m * 60_000 < end; m += 5) minutes.push(m)
  const frames = curve.filter((c) => c.frame)
  const peak = frames.reduce((best, c) => (mine(c.blue) > mine(best.blue) ? c : best), frames[0] ?? curve[0])
  const low = frames.reduce((worst, c) => (mine(c.blue) < mine(worst.blue) ? c : worst), frames[0] ?? curve[0])
  const summary =
    `Win chance peaked at ${Math.round(mine(peak.blue) * 100)}% at ${clock(peak.ms)} and ` +
    `was lowest at ${Math.round(mine(low.blue) * 100)}% at ${clock(low.ms)}` +
    (won === null ? '.' : `; the game ended in a ${won ? 'win' : 'loss'}.`)

  return (
    <figure className="min-w-0">
      <div className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-1.5">
        <div className="tnum relative h-44 text-[10px] text-ink-faint sm:h-52" aria-hidden>
          <span className="absolute right-0 top-0 -translate-y-1/2">100%</span>
          <span className="absolute right-0 top-1/2 -translate-y-1/2">50%</span>
          <span className="absolute bottom-0 right-0 translate-y-1/2">0%</span>
        </div>
        <div
          className="relative h-44 border-b border-l border-line sm:h-52"
          role="img"
          aria-label={summary}
        >
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0 size-full overflow-visible"
            aria-hidden
          >
            <defs>
              <clipPath id={`above-${uid}`}>
                <rect x="0" y="0" width="100" height="50" />
              </clipPath>
              <clipPath id={`below-${uid}`}>
                <rect x="0" y="50" width="100" height="50" />
              </clipPath>
            </defs>
            <line x1="0" x2="100" y1="25" y2="25" stroke="var(--color-line-soft)" vectorEffect="non-scaling-stroke" />
            <line x1="0" x2="100" y1="75" y2="75" stroke="var(--color-line-soft)" vectorEffect="non-scaling-stroke" />
            <line
              x1="0"
              x2="100"
              y1="50"
              y2="50"
              stroke="var(--color-line)"
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
            <path
              d={area}
              fill="color-mix(in srgb, var(--color-win) 22%, transparent)"
              clipPath={`url(#above-${uid})`}
            />
            <path
              d={area}
              fill="color-mix(in srgb, var(--color-loss) 22%, transparent)"
              clipPath={`url(#below-${uid})`}
            />
            <path
              d={line}
              fill="none"
              stroke="var(--color-ink)"
              strokeWidth="1.75"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
          {moments.map((m, i) => (
            <span
              key={m.start_ms}
              className="display absolute grid size-5 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-deep text-[11px] font-700 text-gold-bright ring-1 ring-gold"
              style={{ left: `${x(m.start_ms)}%`, top: `${y(at(m.start_ms))}%` }}
              title={`${clock(m.start_ms)}: ${m.text}`}
              aria-hidden
            >
              {i + 1}
            </span>
          ))}
          {won !== null && (
            <span
              className="absolute right-1 -translate-y-[130%] rounded-sm bg-deep/80 px-1 text-[10px] font-600"
              style={{
                top: `${y(mine(curve[curve.length - 1].blue))}%`,
                color: won ? 'var(--color-win)' : 'var(--color-loss)',
              }}
              aria-hidden
            >
              {won ? 'Win' : 'Loss'}
            </span>
          )}
        </div>
        <div />
        <div className="tnum relative mt-1 h-4 text-[10px] text-ink-faint" aria-hidden>
          {minutes.map((m) => (
            <span
              key={m}
              className="absolute -translate-x-1/2"
              style={{ left: `${x(m * 60_000)}%` }}
            >
              {m}
            </span>
          ))}
        </div>
      </div>
      <figcaption className="mt-2 text-xs leading-relaxed text-ink-dim">{summary}</figcaption>
      <details className="mt-1 text-xs text-ink-faint">
        <summary className="cursor-pointer">Minute by minute</summary>
        <table className="tnum mt-1 border-collapse">
          <thead>
            <tr>
              <th className="py-0.5 pr-4 text-left font-500">Minute</th>
              <th className="py-0.5 text-right font-500">Win chance</th>
            </tr>
          </thead>
          <tbody>
            {frames.map((c) => (
              <tr key={c.ms}>
                <td className="py-0.5 pr-4">{clock(c.ms)}</td>
                <td className="py-0.5 text-right">{Math.round(mine(c.blue) * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
