import { Link } from 'react-router-dom'

import type { Analytics } from '../../lib/api'
import { pct, scoreColor, winRateColor } from '../../lib/format'
import { gamesCovered } from '../../lib/profileScope'

/** The five most played champions over the games in scope, with a way to the rest. */
export default function MostPlayed({
  analytics,
  championsPath,
}: {
  analytics: Analytics
  championsPath: string
}) {
  const top = analytics.champions.slice(0, 5)
  if (top.length === 0) return null
  return (
    <section className="frame">
      <header className="flex items-baseline justify-between border-b border-line-soft px-4 py-2.5">
        <h2 className="eyebrow">
          Most played,{' '}
          {gamesCovered({ games: analytics.games_analysed, total: analytics.stored_total, scope: analytics.scope })}
        </h2>
      </header>
      <ul className="divide-y divide-line-soft">
        {top.map((c) => (
          <li key={c.champion.id} className="flex items-center gap-2.5 px-4 py-2">
            {c.champion.icon_url && (
              <img src={c.champion.icon_url} alt="" className="size-8 rounded-sm" loading="lazy" decoding="async" />
            )}
            <div className="min-w-0 flex-1">
              <p className="display truncate text-[15px] font-600 text-ink">{c.champion.name}</p>
              <p className="tnum text-xs text-ink-faint">
                {c.kda.toFixed(2)} KDA
                {c.avg_score !== null && (
                  <>
                    {', score '}
                    <span style={{ color: scoreColor(c.avg_score) }}>{c.avg_score.toFixed(1)}</span>
                  </>
                )}
              </p>
            </div>
            <div className="text-right">
              <p className="tnum text-sm font-600" style={{ color: winRateColor(c.win_rate, 0.6) }}>
                {pct(c.win_rate)}
              </p>
              <p className="tnum text-xs text-ink-faint">{c.games}g</p>
            </div>
          </li>
        ))}
      </ul>
      <Link
        to={championsPath}
        className="block border-t border-line-soft px-4 py-2 text-xs text-ink-dim transition-colors hover:text-gold-bright"
      >
        All {analytics.champions.length} champions
      </Link>
    </section>
  )
}
