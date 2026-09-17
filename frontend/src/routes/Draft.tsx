import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import ChampionPicker from '../components/ChampionPicker'
import PositionIcon from '../components/PositionIcon'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { api, PLATFORMS, POSITIONS, type DraftResponse } from '../lib/api'
import { compact, parseRiotId, pct } from '../lib/format'

/**
 * Draft assistant.
 *
 * Every suggestion shows its reasoning. A draft tool that just says "pick
 * Malphite" is one nobody trusts when it matters, so the baseline, the matchup
 * sample and the mastery weighting are all visible on the card.
 */
export default function Draft() {
  const [position, setPosition] = useState('MIDDLE')
  const [enemyLaner, setEnemyLaner] = useState<number | null>(null)
  const [bans, setBans] = useState<number[]>([])
  const [banInput, setBanInput] = useState<number | null>(null)
  const [riotId, setRiotId] = useState('')
  const [platform, setPlatform] = useState('euw1')
  // Same escape hatch the tier list has. Without it a thin corpus is a dead
  // end: the request 404s and there is nothing the user can adjust.
  const [minGames, setMinGames] = useState(20)

  const corpus = useQuery({ queryKey: ['corpus'], queryFn: api.corpus })

  // Champion ids are Riot's identifiers, not something a player recognises.
  // The ban chips resolve them to names and portraits.
  const { data: championData } = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })
  const championById = useMemo(
    () => new Map((championData?.champions ?? []).map((c) => [c.id, c])),
    [championData],
  )

  const suggest = useMutation<DraftResponse, unknown, void>({
    mutationFn: () => {
      const parsed = parseRiotId(riotId)
      return api.draft({
        position,
        enemy_laner: enemyLaner,
        bans,
        min_games: minGames,
        platform: parsed ? platform : null,
        game_name: parsed?.name ?? null,
        tag_line: parsed?.tag ?? null,
      })
    },
  })

  const empty = corpus.data && corpus.data.total_matches === 0

  function addBan(id: number | null) {
    if (id && !bans.includes(id)) setBans([...bans, id])
    setBanInput(null)
  }

  return (
    <div className="mx-auto max-w-[1280px] px-4 py-6">
      <header className="border-b border-line-soft pb-5">
        <h1 className="display text-[clamp(1.9rem,4vw,2.6rem)] font-700 text-ink">
          Draft assistant
        </h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-ink-dim">
          Pick your role and the champion you're up against. Suggestions weigh the
          champion's baseline, the head-to-head record, and, if you add your Riot ID,
          what you can actually play.
        </p>
      </header>

      {empty ? (
        <div className="mt-6">
          <EmptyState
            title="No matches ingested yet"
            body="Draft advice is built from a corpus of matches. Run the crawler first: python -m scripts.ingest crawl --target 500, then python -m scripts.ingest aggregate."
          />
        </div>
      ) : (
        <div className="mt-5 grid gap-6 lg:grid-cols-[320px_1fr]">
          {/* Controls */}
          <aside className="space-y-4">
            <div>
              <span className="mb-1 block text-xs text-ink-faint">Your role</span>
              <div className="flex flex-wrap gap-1">
                {POSITIONS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setPosition(p.id)}
                    aria-pressed={position === p.id}
                    className={`flex items-center gap-1 border-b-2 px-1.5 pb-1.5 pt-1 font-display text-sm font-600 transition-colors ${
                      position === p.id
                        ? 'border-gold text-gold-bright'
                        : 'border-transparent text-ink-dim hover:text-ink'
                    }`}
                  >
                    <PositionIcon position={p.id} className="size-4" />
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <ChampionPicker
              label="Enemy in your lane"
              value={enemyLaner}
              onChange={setEnemyLaner}
              placeholder="Optional"
            />

            <div>
              <ChampionPicker
                label="Unavailable (banned or picked)"
                value={banInput}
                onChange={addBan}
                placeholder="Add a champion"
              />
              {bans.length > 0 && (
                <ul className="mt-2 flex flex-wrap gap-1">
                  {bans.map((id) => {
                    const champion = championById.get(id)
                    return (
                      <li key={id}>
                        <button
                          onClick={() => setBans(bans.filter((b) => b !== id))}
                          className="flex items-center gap-1.5 rounded-sm border border-line bg-raised py-1 pl-1 pr-2 text-xs text-ink-dim transition-colors hover:border-loss hover:text-loss"
                          title={`Remove ${champion?.name ?? id}`}
                        >
                          {champion?.icon_url && (
                            <img src={champion.icon_url} alt="" className="size-4 rounded-sm" />
                          )}
                          {champion?.name ?? `Champion ${id}`}
                          <span aria-hidden>✕</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>

            <div>
              <span className="mb-1 block text-xs text-ink-faint">
                Your Riot ID (optional, weighs your mastery)
              </span>
              <div className="flex gap-1">
                <select
                  value={platform}
                  onChange={(e) => setPlatform(e.target.value)}
                  className="control h-10 shrink-0 text-sm"
                >
                  {PLATFORMS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <input
                  value={riotId}
                  onChange={(e) => setRiotId(e.target.value)}
                  placeholder="Caps#EUW"
                  className="control h-10 min-w-0 flex-1 px-3 text-sm placeholder:text-ink-faint"
                />
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm text-ink-dim">
              <span className="text-xs text-ink-faint">Min games per champion</span>
              <input
                type="number"
                min={1}
                value={minGames}
                onChange={(e) => setMinGames(Math.max(1, Number(e.target.value) || 1))}
                className="control tnum w-16"
              />
            </label>

            <button
              onClick={() => suggest.mutate()}
              disabled={suggest.isPending}
              className="w-full rounded-sm bg-gold py-2.5 font-display text-sm font-700 tracking-wide text-deep transition-colors hover:bg-gold-bright disabled:opacity-60"
            >
              {suggest.isPending ? 'Working…' : 'Suggest picks'}
            </button>
          </aside>

          {/* Results */}
          <div className="min-w-0">
            {suggest.isPending && <Spinner label="Scoring champions…" />}

            {suggest.isError && (
              <ErrorView error={suggest.error} onRetry={() => suggest.mutate()} />
            )}

            {suggest.isSuccess && (
              <>
                <div className="flex flex-wrap items-baseline gap-x-3 text-xs text-ink-faint">
                  <span>Patch {suggest.data.patch}</span>
                  {suggest.data.enemy_laner && (
                    <span>against {suggest.data.enemy_laner.name}</span>
                  )}
                  <span>
                    {suggest.data.personalised
                      ? 'weighted by your mastery'
                      : 'not personalised'}
                  </span>
                </div>

                <ol className="mt-3 space-y-1.5">
                  {suggest.data.suggestions.map((s, i) => {
                    const delta = s.adjusted_win_rate - s.base_win_rate
                    return (
                      <li
                        key={s.champion.id}
                        className="flex gap-3 border-b border-line-soft px-3 py-2.5 transition-colors hover:bg-raised/30"
                      >
                        <span className="tnum w-5 shrink-0 pt-1 text-xs text-ink-faint">
                          {i + 1}
                        </span>
                        {s.champion.icon_url && (
                          <img
                            src={s.champion.icon_url}
                            alt=""
                            className="size-10 shrink-0 rounded-sm"
                            loading="lazy"
                          />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline gap-x-2">
                            <p className="font-display text-sm font-700 text-ink">
                              {s.champion.name}
                            </p>
                            <p className="tnum text-sm font-600 text-gold-bright">
                              {pct(s.adjusted_win_rate, 1)}
                            </p>
                            {Math.abs(delta) > 0.001 && (
                              <p
                                className="tnum text-xs"
                                style={{
                                  color:
                                    delta > 0 ? 'var(--color-win)' : 'var(--color-loss)',
                                }}
                              >
                                {delta > 0 ? '+' : ''}
                                {(delta * 100).toFixed(1)} vs baseline
                              </p>
                            )}
                          </div>
                          <ul className="mt-0.5 text-xs leading-relaxed text-ink-dim">
                            {s.reasons.map((r, j) => (
                              <li key={j}>{r}</li>
                            ))}
                          </ul>
                        </div>
                        <div className="shrink-0 text-right text-xs text-ink-faint">
                          <p className="tnum">{compact(s.games)} games</p>
                          {s.mastery_points > 0 && (
                            <p className="tnum">{compact(s.mastery_points)} pts</p>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </>
            )}

            {suggest.isIdle && (
              <EmptyState
                title="Set the lane, then ask"
                body="Choose your role and, if the enemy has already locked in, who you're facing. Adding your Riot ID biases the list toward champions you've actually played."
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
