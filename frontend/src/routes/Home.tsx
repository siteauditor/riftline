import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import SearchBar from '../components/SearchBar'
import { api } from '../lib/api'
import { compact, pct, winRateColor } from '../lib/format'

// Two accounts with a real history behind them. The previous EUW example was
// `Caps#EUW`, which resolves to an unranked level 31 with no games: the first
// thing a new visitor clicked landed them on an empty profile.
const EXAMPLES = [
  { platform: 'kr', name: 'Hide on bush', tag: 'KR1', label: 'Hide on bush#KR1' },
  { platform: 'euw1', name: 'J1HUIV', tag: '000', label: 'J1HUIV#000' },
]

/**
 * Landing view.
 *
 * The search is the product, so it stays the first thing. What it did not do
 * before was give any sign of what game this is about: a headline and a field
 * on an empty ground could have been a tax calculator. So the page now opens on
 * the strongest champions in the corpus, rendered with their own key art, which
 * is both the fastest way to say "League of Legends" and a genuinely useful
 * thing to land on.
 */
export default function Home() {
  const meta = useQuery({
    queryKey: ['meta', { minGames: 40 }],
    queryFn: () => api.meta({ minGames: 40 }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
  const top = (meta.data?.rows ?? []).slice(0, 6)

  return (
    <div>
      <section className="border-b border-line-soft">
        <div className="mx-auto max-w-[1280px] px-4 pb-14 pt-20 sm:pt-28">
          {/* Broken by hand. Left to a measure, the rag landed on "read at /
              a glance", which splits the phrase that carries the meaning. */}
          <h1 className="display text-[clamp(2.6rem,6.5vw,4.5rem)] font-700 text-ink">
            Every game you have played,
            <br />
            read at a glance.
          </h1>
          <p className="mt-4 max-w-[52ch] text-[15px] leading-relaxed text-ink-dim">
            Rank, match history, champion mastery and the meta, for any League of
            Legends player. Search a Riot ID to start.
          </p>

          <div className="mt-8 max-w-xl">
            <SearchBar size="large" autoFocus />
          </div>

          <div className="mt-4 flex max-w-xl flex-wrap items-center gap-2 text-sm">
            <span className="text-ink-faint">Try</span>
            {EXAMPLES.map((e) => (
              <Link
                key={e.label}
                to={`/summoner/${e.platform}/${encodeURIComponent(e.name)}/${encodeURIComponent(e.tag)}`}
                className="border-b border-line text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
              >
                {e.label}
              </Link>
            ))}
          </div>
        </div>
      </section>

      {top.length > 0 && (
        <section className="mx-auto max-w-[1280px] px-4 py-10">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 className="display text-2xl font-600 text-ink">Strongest right now</h2>
            <Link
              to="/tierlist"
              className="text-sm text-ink-dim transition-colors hover:text-gold-bright"
            >
              See the full tier list
            </Link>
          </div>
          <p className="mt-1 max-w-[62ch] text-sm text-ink-dim">
            Ranked by the win rate the sample actually supports, over 40 games or
            more, on patch {meta.data?.patch}. A champion at 3-0 is not the
            strongest in the game.
          </p>

          <ul className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {top.map((row) => (
              <li key={row.champion.id}>
                <Link
                  to={`/champions/${row.champion.id}`}
                  className="group block overflow-hidden rounded-sm ring-1 ring-line transition-[box-shadow] hover:ring-gold"
                >
                  {/* Tile art, not a 48px icon. The art is the point. */}
                  <span className="relative block aspect-[3/4] overflow-hidden bg-raised">
                    {row.champion.tile_url && (
                      <img
                        src={row.champion.tile_url}
                        alt=""
                        loading="lazy"
                        className="size-full object-cover object-top"
                      />
                    )}
                    <span
                      aria-hidden
                      className="absolute inset-0"
                      style={{
                        backgroundImage:
                          'linear-gradient(to top, var(--color-deep) 6%, color-mix(in srgb, var(--color-deep) 45%, transparent) 46%, transparent 78%)',
                      }}
                    />
                    <span className="absolute inset-x-0 bottom-0 p-2.5">
                      <span className="display block truncate text-[15px] font-600 text-ink">
                        {row.champion.name}
                      </span>
                      <span className="mt-0.5 flex items-baseline gap-1.5">
                        <span
                          className="tnum display text-lg font-700"
                          style={{ color: winRateColor(row.confidence_win_rate, 0.52) }}
                        >
                          {pct(row.confidence_win_rate, 1)}
                        </span>
                        <span className="tnum text-[11px] text-ink-faint">
                          {compact(row.games)} games
                        </span>
                      </span>
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
