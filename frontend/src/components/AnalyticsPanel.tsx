import type { Analytics } from '../lib/api'
import { pct, positionLabel } from '../lib/format'

/**
 * Play style: which roles, which champion classes, and when they play.
 *
 * Every number comes from matches already in storage, so this panel costs no
 * Riot budget and never blocks on a rate limit. The flip side is that it
 * describes the games we hold rather than a whole season, which the footer says
 * plainly rather than leaving the reader to assume.
 *
 * The profile owns the query and passes the result in, because it has to be
 * read after the match list has stored the player's games, not beside it.
 */
export default function AnalyticsPanel({ data }: { data: Analytics | undefined }) {
  if (!data || data.games_analysed === 0) return null

  const peakGames = Math.max(...data.activity_utc, 1)

  // The server reports UTC buckets on purpose; the shift to local happens here,
  // where the viewer's timezone is actually known.
  //
  // The offset is rounded to whole hours *before* the shift, not after. Rounding
  // afterwards turns a +05:30 offset into a fractional bucket index that can
  // land on 24, which reads back as undefined and silently drops an hour of
  // games. India and Newfoundland both hit that.
  const offsetHours = Math.round(-new Date().getTimezoneOffset() / 60)
  const local = Array.from({ length: 24 }, (_, hour) => {
    const utcHour = (((hour - offsetHours) % 24) + 24) % 24
    return data.activity_utc[utcHour] ?? 0
  })

  return (
    <section className="frame">
      <header className="border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">Play style</h2>
      </header>

      <div className="space-y-4 px-4 py-3">
        <div>
          <p className="mb-1.5 text-xs text-ink-faint">Role share</p>
          <ul className="space-y-1">
            {data.roles.map((role) => (
              <li key={role.position} className="flex items-center gap-2 text-xs">
                <span className="w-14 shrink-0 text-ink-dim">
                  {positionLabel(role.position)}
                </span>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                  <span
                    className="block h-full"
                    style={{
                      width: `${role.share * 100}%`,
                      background: 'var(--accent)',
                    }}
                  />
                </span>
                <span className="tnum w-9 shrink-0 text-right text-ink">
                  {pct(role.share)}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {data.classes.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs text-ink-faint">Champion classes</p>
            <ul className="space-y-1">
              {data.classes.slice(0, 4).map((klass) => (
                <li key={klass.tag} className="flex items-center gap-2 text-xs">
                  <span className="w-14 shrink-0 truncate text-ink-dim">{klass.tag}</span>
                  <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
                    <span
                      className="block h-full bg-gold/70"
                      style={{ width: `${klass.share * 100}%` }}
                    />
                  </span>
                  <span className="tnum w-9 shrink-0 text-right text-ink">
                    {pct(klass.share)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <p className="mb-1.5 text-xs text-ink-faint">When they play (your local time)</p>
          <div className="flex h-10 items-end gap-[2px]" aria-hidden>
            {local.map((games, hour) => (
              <span
                key={hour}
                title={`${String(hour).padStart(2, '0')}:00, ${games} game${games === 1 ? '' : 's'}`}
                className="flex-1 rounded-t-[1px] bg-gold/60"
                style={{ height: `${Math.max(4, (games / peakGames) * 100)}%` }}
              />
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-ink-faint">
            <span>00</span>
            <span>06</span>
            <span>12</span>
            <span>18</span>
            <span>23</span>
          </div>
        </div>

        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-line-soft pt-2.5 text-xs">
          <Pair label="KDA" value={data.totals.kda.toFixed(2)} />
          <Pair label="CS/min" value={data.totals.cs_per_min.toFixed(1)} />
          <Pair label="Vision" value={data.totals.vision_per_game.toFixed(0)} />
          <Pair label="Win rate" value={pct(data.totals.win_rate)} />
        </dl>

        <p className="text-[11px] leading-relaxed text-ink-faint">
          From {data.games_analysed} stored games, not the full season. Loading more
          match history deepens this.
        </p>
      </div>
    </section>
  )
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="tnum font-600 text-ink">{value}</dd>
    </div>
  )
}
