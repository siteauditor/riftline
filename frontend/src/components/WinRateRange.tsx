import { pct } from '../lib/format'

// A fixed scale, so two rows' bars can be compared by eye. Thin samples run past
// it (a 70% over 20 games spans about 48 to 85) and are clipped at the edge
// rather than rescaling the whole list around its widest row.
const SCALE_LOW = 0.35
const SCALE_HIGH = 0.75

const place = (value: number) =>
  ((Math.min(Math.max(value, SCALE_LOW), SCALE_HIGH) - SCALE_LOW) / (SCALE_HIGH - SCALE_LOW)) *
  100

/**
 * A win rate as the range its sample supports.
 *
 * The list is ranked on the low end of the range, which used to be the only
 * number shown, so most S tiers read below 50% (Kalista S at 48.3% on 16.18)
 * and looked like losing picks. The raw rate leads now, and the bar underneath
 * shows how far the sample lets it move: a 70% over 20 games is a wide bar that
 * may well sit under 50%, and that is why it ranks below a 63% over 79.
 */
export default function WinRateRange({
  rate,
  low,
  high,
  games,
}: {
  rate: number
  low: number
  high: number
  games: number
}) {
  // Gold only when even the low end is a winning rate: that is a pick the
  // sample actually backs, not one that merely happened to win.
  const backed = low >= 0.5
  return (
    <span
      className="inline-flex flex-col items-end gap-1"
      title={
        `${pct(rate, 1)} over ${games.toLocaleString()} games. The sample supports ` +
        `anything from ${pct(low, 1)} to ${pct(high, 1)}, and the list ranks on the low end.`
      }
    >
      <span className="tnum display text-xl font-700 leading-none text-ink">{pct(rate, 1)}</span>
      <span className="relative block h-1.5 w-28 rounded-full bg-raised" aria-hidden>
        <span
          className="absolute inset-y-0 rounded-full"
          style={{
            left: `${place(low)}%`,
            width: `${Math.max(place(high) - place(low), 2)}%`,
            background: backed
              ? 'var(--color-gold-bright)'
              : 'color-mix(in srgb, var(--color-ink-dim) 55%, transparent)',
          }}
        />
        {/* 50%, the line that matters. */}
        <span
          className="absolute -inset-y-[3px] w-px bg-ink-faint"
          style={{ left: `${place(0.5)}%` }}
        />
      </span>
      <span className="tnum text-[11px] leading-none text-ink-faint">
        {Math.round(low * 100)} to {Math.round(high * 100)}
      </span>
    </span>
  )
}
