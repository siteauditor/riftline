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
  size = 'lg',
  rankedOn = 'low',
}: {
  rate: number
  low: number
  high: number
  games: number
  /** `sm` for a row of text-sm, as in the matchup tables. */
  size?: 'lg' | 'sm'
  /** What the surrounding list is ordered by: the tier list reads the low
   *  end, the matchup tables the middle. */
  rankedOn?: 'low' | 'middle'
}) {
  // Gold only when even the low end is a winning rate: that is a pick the
  // sample actually backs, not one that merely happened to win.
  const backed = low >= 0.5
  return (
    <span
      className="inline-flex flex-col items-end gap-1"
      title={
        `${pct(rate, 1)} over ${games.toLocaleString('en-US')} games. The sample supports ` +
        `anything from ${pct(low, 1)} to ${pct(high, 1)}, and the list ranks on ${
          rankedOn === 'low' ? 'the low end' : 'the middle of that'
        }.`
      }
    >
      <span
        className={`tnum display leading-none text-ink ${
          size === 'sm' ? 'text-[15px] font-600' : 'text-xl font-700'
        }`}
      >
        {pct(rate, 1)}
      </span>
      <span
        className={`relative block rounded-full bg-raised ${size === 'sm' ? 'h-1 w-20' : 'h-1.5 w-28'}`}
        aria-hidden
      >
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
