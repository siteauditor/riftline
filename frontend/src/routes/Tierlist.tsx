import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import PositionIcon from '../components/PositionIcon'
import SliceFilters, { SliceSummary, type SliceValue } from '../components/SliceFilters'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { api, type ChampionMetaRow } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'

/**
 * Tier badges: a ramp of treatments, not just of hues.
 *
 * Filled, tinted, solid, outlined, bare. B and C were both `raised` and differed
 * only in text colour, which is not a step a reader can see at 12px, and no
 * colour-only ramp survives a colourblind reader.
 */
const TIER_STYLE: Record<string, { bg: string; fg: string; ring?: string }> = {
  S: { bg: 'var(--color-gold)', fg: 'var(--color-deep)' },
  A: {
    bg: 'color-mix(in srgb, var(--color-gold) 26%, transparent)',
    fg: 'var(--color-gold-bright)',
  },
  B: { bg: 'var(--color-raised)', fg: 'var(--color-ink)' },
  C: { bg: 'transparent', fg: 'var(--color-ink-dim)', ring: 'var(--color-line)' },
  D: { bg: 'transparent', fg: 'var(--color-ink-faint)' },
}

type SortKey = 'confidence_win_rate' | 'win_rate' | 'pick_rate' | 'ban_rate' | 'games'

const COLUMNS: { key: SortKey; label: string; hint: string }[] = [
  { key: 'confidence_win_rate', label: 'Adjusted', hint: 'Win rate we can defend at this sample size' },
  { key: 'win_rate', label: 'Win rate', hint: 'Raw wins over games' },
  { key: 'pick_rate', label: 'Pick', hint: 'Share of games this champion was picked' },
  { key: 'ban_rate', label: 'Ban', hint: 'Share of games this champion was banned' },
  { key: 'games', label: 'Games', hint: 'Sample size' },
]

export default function Tierlist() {
  const [slice, setSlice] = useState<SliceValue>({
    patch: null,
    queueId: 420,
    position: null,
    bracket: null,
    minGames: 20,
  })
  const [sort, setSort] = useState<SortKey>('confidence_win_rate')

  const corpus = useQuery({ queryKey: ['corpus'], queryFn: api.corpus })
  const meta = useQuery({
    queryKey: ['meta', slice],
    queryFn: () => api.meta(slice),
    retry: false,
  })
  const position = slice.position

  const rows: ChampionMetaRow[] = [...(meta.data?.rows ?? [])].sort((a, b) => {
    const value = (r: ChampionMetaRow) => r[sort] as number
    return value(b) - value(a)
  })

  const empty = corpus.data && corpus.data.total_matches === 0

  return (
    <div className="mx-auto max-w-[1280px] px-4 py-6">
      <header className="border-b border-line-soft pb-5">
        <h1 className="display text-[clamp(1.9rem,4vw,2.6rem)] font-700 text-ink">
          Champion tier list
        </h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-ink-dim">
          Ranked by the win rate the sample actually supports, not by raw win rate.
          A champion at 3-0 is not the strongest in the game, and this list doesn't
          pretend otherwise.
        </p>
      </header>

      {empty ? (
        <div className="mt-6">
          <EmptyState
            title="No matches ingested yet"
            body="Tier lists are built from a corpus of matches. Run the crawler to collect some: python -m scripts.ingest crawl --target 500, then python -m scripts.ingest aggregate."
          />
        </div>
      ) : (
        <>
          <div className="mt-5">
            <SliceFilters
              value={slice}
              onChange={(next) => setSlice((s) => ({ ...s, ...next }))}
              allowAllPositions
              summary={
                meta.data && (
                  <SliceSummary
                    patch={meta.data.patch}
                    matches={meta.data.sample_matches}
                    bracket={meta.data.rank_bracket}
                  />
                )
              }
            />
          </div>

          {meta.isLoading && (
            <div className="py-8">
              <Spinner label="Loading champion statistics…" />
            </div>
          )}

          {meta.isError && (
            <div className="mt-5">
              <ErrorView error={meta.error} onRetry={() => meta.refetch()} />
            </div>
          )}

          {rows.length > 0 && rows.every((r) => r.tier === null) && (
            <p className="mt-4 border-l-2 border-gold/50 py-1 pl-3 text-sm text-ink-dim">
              Only {rows.length}{' '}
              {rows.length === 1 ? 'champion has' : 'champions have'} enough games
              in this slice, which is too few to rank against each other, so the
              tier column is blank. The numbers below are still real. Lower
              &ldquo;min games&rdquo; to widen the list, or ingest more matches.
            </p>
          )}

          {rows.length > 0 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-xs text-ink-faint">
                    <th className="w-9 py-2.5 text-left font-500">#</th>
                    <th className="w-12 py-2.5 text-left font-500">Tier</th>
                    <th className="py-2.5 text-left font-500">Champion</th>
                    {COLUMNS.map((c) => (
                      <th
                        key={c.key}
                        aria-sort={sort === c.key ? 'descending' : 'none'}
                        className="py-2.5 text-right font-500"
                      >
                        <button
                          onClick={() => setSort(c.key)}
                          title={c.hint}
                          className={`border-b-2 pb-0.5 transition-colors ${
                            sort === c.key
                              ? 'border-gold text-gold-bright'
                              : 'border-transparent hover:text-ink'
                          }`}
                        >
                          {c.label}
                        </button>
                      </th>
                    ))}
                    <th className="py-2.5 text-right font-500">KDA</th>
                    <th className="py-2.5 text-right font-500">CS/m</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const style = (r.tier && TIER_STYLE[r.tier]) || TIER_STYLE.D
                    return (
                      <tr
                        key={`${r.champion.id}-${r.position}`}
                        className="border-b border-line-soft transition-colors hover:bg-raised/40"
                      >
                        <td className="tnum py-2.5 text-xs text-ink-faint">{i + 1}</td>
                        <td className="py-2.5">
                          {r.tier ? (
                            <span
                              className="inline-grid size-7 place-items-center rounded-sm font-display text-sm font-800"
                              style={{
                                background: style.bg,
                                color: style.fg,
                                boxShadow: style.ring ? `inset 0 0 0 1px ${style.ring}` : undefined,
                              }}
                            >
                              {r.tier}
                            </span>
                          ) : (
                            <span
                              className="text-ink-faint"
                              title="Too few champions in this slice to rank them against each other"
                            >
                              –
                            </span>
                          )}
                        </td>
                        <td className="py-2.5">
                          <Link
                            to={`/champions/${r.champion.id}?position=${r.position}`}
                            className="group flex items-center gap-3"
                          >
                            {r.champion.icon_url && (
                              <img
                                src={r.champion.icon_url}
                                alt=""
                                className="size-10 rounded-sm ring-1 ring-line transition-[box-shadow] group-hover:ring-gold"
                                loading="lazy"
                              />
                            )}
                            <div className="min-w-0">
                              <p className="display truncate text-[17px] font-600 text-ink transition-colors group-hover:text-gold-bright">
                                {r.champion.name}
                              </p>
                              {!position && (
                                <p className="flex items-center gap-1 text-[11px] text-ink-faint">
                                  <PositionIcon
                                    position={r.position}
                                    className="size-[13px]"
                                  />
                                  {positionLabel(r.position)}
                                </p>
                              )}
                            </div>
                          </Link>
                        </td>
                        <td className="tnum display py-2.5 text-right text-xl font-700 text-ink">
                          {pct(r.confidence_win_rate, 1)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-dim">
                          {pct(r.win_rate, 1)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-dim">
                          {pct(r.pick_rate, 1)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-dim">
                          {pct(r.ban_rate, 1)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-faint">
                          {compact(r.games)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-dim">
                          {r.avg_kda.toFixed(2)}
                        </td>
                        <td className="tnum py-2.5 text-right text-ink-dim">
                          {r.avg_cs_per_min.toFixed(1)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
