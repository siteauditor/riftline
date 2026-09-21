import type { ItemFigures } from '../../lib/api'

/**
 * When the item is bought: the middle half of first purchases as a band on a
 * game clock, with the median marked. From timelines, so it says how many
 * games had one.
 */
export default function ItemTiming({ figures, finished }: { figures: ItemFigures; finished: boolean }) {
  const { minute_p25: low, minute_p50: mid, minute_p75: high } = figures
  if (mid === null || low === null || high === null) return null
  // A clock long enough for the late items, and never shorter than a game.
  const span = Math.max(30, Math.ceil((high + 4) / 5) * 5)
  const at = (minute: number) => `${Math.min(100, (minute / span) * 100)}%`
  const verb = finished ? 'Finished' : 'Bought'

  return (
    <section>
      <h2 className="display text-base font-600 text-ink">When it's bought</h2>
      <p className="mt-1 text-sm text-ink-dim">
        {verb} at a median of <span className="tnum font-600 text-ink">{minutes(mid)}</span>, most
        often between {clock(low)} and {clock(high)} minutes.
      </p>
      <div className="relative mt-4 h-2 bg-raised" aria-hidden>
        <span className="absolute inset-y-0 bg-accent/60" style={{ left: at(low), right: `calc(100% - ${at(high)})` }} />
        <span className="absolute -inset-y-1 w-0.5 bg-ink" style={{ left: at(mid) }} />
      </div>
      <div className="tnum mt-1 flex justify-between text-[11px] text-ink-faint" aria-hidden>
        {Array.from({ length: span / 5 + 1 }, (_, i) => (
          <span key={i}>{i * 5}</span>
        ))}
      </div>
      <p className="mt-2 text-xs text-ink-faint">
        The first purchase of the item in {figures.timed.toLocaleString('en-US')} games with a
        timeline, in minutes.
      </p>
    </section>
  )
}

function clock(value: number): string {
  return value.toFixed(value < 10 ? 1 : 0)
}

function minutes(value: number): string {
  if (value < 1) return 'under a minute'
  return `${value.toFixed(value < 10 ? 1 : 0)} minutes`
}
