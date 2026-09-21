import type { CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { PLATFORMS, api, type LeaderboardResponse } from '../lib/api'
import Crest from '../components/Crest'
import RankBadge from '../components/RankBadge'
import { ErrorView, Spinner } from '../components/StateViews'
import { compact, pct, tierColor, tierLabel, timeAgo } from '../lib/format'

/**
 * Shown while `/leaderboard/slices` is in flight, so the filters are usable on
 * the first paint. The server is the authority: it decides which tiers and
 * regions it will actually serve, and these going stale is exactly the drift
 * that duplicating the list invites.
 */
const FALLBACK = {
  apex_tiers: ['MASTER', 'GRANDMASTER', 'CHALLENGER'],
  tiers: [
    'MASTER', 'GRANDMASTER', 'CHALLENGER',
    'DIAMOND', 'EMERALD', 'PLATINUM', 'GOLD', 'SILVER', 'BRONZE', 'IRON',
  ],
  divisions: ['I', 'II', 'III', 'IV'],
  queues: [
    { id: 420, label: 'Ranked Solo/Duo' },
    { id: 440, label: 'Ranked Flex' },
  ],
  platforms: PLATFORMS,
}
const PER_PAGE = 50

// Riot sends ladders without names, so each unnamed player costs one lookup,
// and the server names up to 25 a request while the key allows. A page with
// unnamed rows asks again on its own instead of telling the reader to come
// back: on a Bronze page nobody is named from our stored games, and 50 names
// are two requests' worth, so the second follows quickly.
const NAME_POLL_MS = 3_000
// When the server held names back to keep the key's reserve, it says when the
// key will have room and the page asks then. A call frees two minutes after it
// was made, and a fixed 48 seconds of asking gave up first: measured on EUW
// Bronze IV on 2026-09-22, pages 5 to 8 were still held when it stopped.
const NAME_POLL_MAX_MS = 125_000
const NAME_POLLS = 8

/** Rows that can still get a name. Riot has no account behind some ladder
 *  entries, and those are not worth waiting for. */
const pendingNames = (d: LeaderboardResponse) =>
  d.rows.filter((r) => !r.riot_id && !r.no_riot_id).length

export default function Leaderboard() {
  // Filters live in the URL, the way the champion page already does it, so a
  // ladder can be linked to.
  const [search, setSearch] = useSearchParams()

  const slicesQuery = useQuery({
    queryKey: ['leaderboard-slices'],
    queryFn: api.leaderboardSlices,
    // Region and tier lists are fixed for the life of a deployment.
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
  })
  const slices = slicesQuery.data ?? FALLBACK

  // URL params are user input. `Number('abc')` is NaN, `Math.max(1, NaN)` is
  // NaN, and `String(NaN)` went on the wire as `page=NaN` for FastAPI to reject
  // with a 422 that surfaced as "Something went wrong".
  const intParam = (key: string, fallback: number) => {
    const value = Number(search.get(key))
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : fallback
  }
  const platform = search.get('platform') ?? 'euw1'
  const tier = (search.get('tier') ?? 'CHALLENGER').toUpperCase()
  const division = (search.get('division') ?? 'I').toUpperCase()
  const queueId = intParam('queue', 420)
  const page = intParam('page', 1)
  const isApex = slices.apex_tiers.includes(tier)

  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(search)
    for (const [k, v] of Object.entries(patch)) next.set(k, v)
    // Any filter change invalidates the page number.
    if (!('page' in patch)) next.set('page', '1')
    setSearch(next, { replace: true })
  }

  // Apex ignores the division server-side, so including it would key two
  // cache entries to one byte-identical response.
  const effectiveDivision = isApex ? 'I' : division
  const queryKey = ['leaderboard', platform, queueId, tier, effectiveDivision, page]
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey,
    queryFn: () =>
      api.leaderboard(platform, {
        queueId, tier, division: effectiveDivision, page, perPage: PER_PAGE,
      }),
    // The server caches a snapshot for fifteen minutes, so refetching faster
    // than that buys nothing, apart from the names below.
    staleTime: 300_000,
    retry: false,
    // Keep the previous page on screen while the next loads, instead of
    // dropping to a spinner and jumping the scroll position on every click.
    placeholderData: (previous) => previous,
    // Unnamed rows fill in while the page is open. `dataUpdateCount` is every
    // answer for this key, the first included, so the page stops asking after
    // NAME_POLLS more and names the rest on a later visit.
    refetchInterval: (q) => {
      const d = q.state.data
      if (!d || pendingNames(d) === 0 || q.state.dataUpdateCount > NAME_POLLS) return false
      if (!d.names_held_back) return NAME_POLL_MS
      // A second past the estimate, so the slots have freed when it lands.
      const wait = ((d.names_retry_after ?? 0) + 1) * 1000
      return Math.min(Math.max(wait, NAME_POLL_MS), NAME_POLL_MAX_MS)
    },
    refetchIntervalInBackground: false,
  })

  const data = query.data
  const answers = queryClient.getQueryState(queryKey)?.dataUpdateCount ?? 0
  const pending = data ? pendingNames(data) : 0
  const noAccount = data ? data.rows.filter((r) => r.no_riot_id).length : 0
  // Still asking, and this is the page's own answer rather than the previous
  // page shown while it loads.
  const lookingUp = pending > 0 && answers <= NAME_POLLS && !query.isPlaceholderData

  // The ladder being read is the subject, so it sets the page's accent. On a
  // site about rank the colour carries information rather than decorating.
  const accent = tierColor(tier)
  const regionLabel = slices.platforms.find((p) => p.id === platform)?.label ?? platform
  const queueLabel = slices.queues.find((q) => q.id === queueId)?.label ?? 'this queue'

  // A slice is one tier and one division, so every row would carry the same
  // badge. The heading states it once instead, and the column comes back only
  // if the rows ever disagree.
  const mixedRanks =
    new Set((data?.rows ?? []).map((r) => r.tier + '/' + r.division)).size > 1

  return (
    <div
      className="mx-auto max-w-[1060px] space-y-5 px-4 py-6"
      style={{ '--accent': accent } as CSSProperties}
    >
      <header className="flex items-center gap-4">
        {/* The ladder's own emblem: on this page the rank is the subject.
            Hidden below sm, where 128px of emblem above a 32px headline would
            push the filter row off the first screen. */}
        <Crest tier={tier} size="hero" className="hidden sm:block" />
        <div className="min-w-0">
          <p className="eyebrow">{regionLabel} ladder</p>
          <h1
            className="display text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em]"
            style={{ color: accent }}
          >
            {tierLabel(tier, division)}
          </h1>
          <p className="mt-2 max-w-[70ch] text-sm leading-relaxed text-ink-dim">
            {queueLabel}. Riot's ladder carries no names, so a player
            reads as unknown until we have seen them in a stored match or looked
            them up, which happens gradually as pages are viewed.
          </p>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        <Field label="Region">
          <Select value={platform} onChange={(v) => set({ platform: v })}>
            {/* A URL can name a region the server does not list. Without this
                the select silently displayed the first option while the query
                fetched something else. */}
            {!slices.platforms.some((p) => p.id === platform) && (
              <option value={platform}>{platform}</option>
            )}
            {slices.platforms.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </Select>
        </Field>
        <Field label="Queue">
          <Select value={String(queueId)} onChange={(v) => set({ queue: v })}>
            {slices.queues.map((q) => (
              <option key={q.id} value={String(q.id)}>{q.label}</option>
            ))}
          </Select>
        </Field>
        <Field label="Tier">
          <Select value={tier} onChange={(v) => set({ tier: v })}>
            {!slices.tiers.includes(tier) && <option value={tier}>{tier}</option>}
            {slices.tiers.map((t) => (
              <option key={t} value={t}>{t[0] + t.slice(1).toLowerCase()}</option>
            ))}
          </Select>
        </Field>
        {!isApex && (
          <Field label="Division">
            <Select value={division} onChange={(v) => set({ division: v })}>
              {slices.divisions.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </Select>
          </Field>
        )}
        {data && (
          <p className="ml-auto text-ink-faint">
            {data.total_on_ladder
              ? `${compact(data.total_on_ladder)} players`
              : `${compact(data.total)} scanned, ranked among themselves`}
            {data.truncated && data.total_on_ladder
              ? `, top ${compact(data.total)} shown`
              : ''}
            {data.fetched_at && `, snapshot ${timeAgo(data.fetched_at)}`}
            {`, ${data.named_on_page} of ${data.rows.length} named here`}
            {noAccount > 0 && `, ${noAccount} with no Riot ID`}
            {pending > 0 &&
              (!lookingUp
                ? ', the rest fill in on a later visit'
                : data.names_held_back
                  ? ", the rest follow when Riot's rate limit allows"
                  : ', looking up the rest')}
          </p>
        )}
      </div>

      {query.isLoading && <Spinner label="Loading the ladder" />}
      {query.isError && (
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      )}

      {data && (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-ink-faint">
                  <th
                    className="py-1.5 text-right font-500"
                    title={
                      data.total_on_ladder
                        ? 'Position on the ladder, ordered by LP.'
                        : 'Position within the rows we scanned, ordered by LP. ' +
                          'Riot gives no total for this tier and does not promise ' +
                          'an order, so this is not a ladder rank.'
                    }
                  >
                    #
                  </th>
                  <th className="py-2 pl-4 text-left font-500">Player</th>
                  {mixedRanks && <th className="py-2 text-left font-500">Rank</th>}
                  <th className="py-2 text-right font-500">LP</th>
                  <th className="py-2 text-right font-500">W / L</th>
                  <th className="py-2 pl-6 text-right font-500">Win rate</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => {
                  const [name, tagLine] = (row.riot_id ?? '').split('#')
                  return (
                    <tr
                      key={row.puuid}
                      className="lift border-b border-line-soft"
                    >
                      <td className="tnum display py-2.5 text-right text-base font-600 text-ink-faint">
                        {row.position}
                      </td>
                      <td className="py-2.5 pl-4">
                        {name && tagLine ? (
                          <Link
                            to={`/summoner/${data.platform}/${encodeURIComponent(name)}/${encodeURIComponent(tagLine)}`}
                            className="display text-[17px] font-600 text-ink transition-colors hover:text-gold-bright"
                          >
                            {name}
                            <span className="ml-0.5 text-sm font-400 text-ink-faint">
                              #{tagLine}
                            </span>
                          </Link>
                        ) : row.no_riot_id ? (
                          <span
                            className="text-ink-faint"
                            title="Riot has no account record behind this ladder entry, so there is no name to show."
                          >
                            No Riot ID
                          </span>
                        ) : (
                          <span
                            className="text-ink-faint"
                            title="Riot sends ladders without names, so each one is looked up separately, a few at a time, within the rate limit Riot sets. Once found, a name is kept."
                          >
                            {lookingUp ? 'Looking up name' : 'Name not found yet'}
                          </span>
                        )}
                        {row.inactive && (
                          <span className="ml-2 text-[11px] text-ink-faint">inactive</span>
                        )}
                        {row.hot_streak && (
                          <span className="ml-2 text-[11px] text-gold-bright">hot streak</span>
                        )}
                      </td>
                      {mixedRanks && (
                        <td className="py-2.5">
                          <RankBadge tier={row.tier} division={row.division} />
                        </td>
                      )}
                      <td
                        className="tnum display py-2.5 text-right text-lg font-700"
                        style={{ color: accent }}
                      >
                        {row.league_points.toLocaleString()}
                      </td>
                      <td className="tnum py-2.5 text-right text-ink-dim">
                        <span className="text-win">{row.wins}</span>
                        <span className="mx-1 text-ink-faint">/</span>
                        <span className="text-loss">{row.losses}</span>
                      </td>
                      <td className="py-2.5 pl-6">
                        {row.games ? (
                          <div className="flex items-center justify-end gap-2.5">
                            <span
                              aria-hidden
                              className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-raised sm:block"
                            >
                              <span
                                className="block h-full bg-win"
                                style={{ width: `${row.win_rate * 100}%` }}
                              />
                            </span>
                            <span
                              className={`tnum w-12 text-right font-600 ${
                                row.win_rate >= 0.5 ? 'text-ink' : 'text-ink-dim'
                              }`}
                            >
                              {pct(row.win_rate, 1)}
                            </span>
                          </div>
                        ) : (
                          <p className="tnum text-right text-ink-faint">-</p>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {data.rows.length === 0 && (
            <p className="py-6 text-center text-sm text-ink-faint">
              Nothing on this page. {data.total > 0
                ? `This ladder holds ${compact(data.total)} rows.`
                : 'This ladder is empty right now.'}
            </p>
          )}

          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => set({ page: String(page - 1) })}
              className="rounded-sm border border-line px-3 py-1.5 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:pointer-events-none disabled:opacity-35"
            >
              Previous
            </button>
            <span className="tnum text-ink-faint">Page {page}</span>
            <button
              type="button"
              disabled={!data.has_more}
              onClick={() => set({ page: String(page + 1) })}
              className="rounded-sm border border-line px-3 py-1.5 text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:pointer-events-none disabled:opacity-35"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="text-ink-faint">{label}</span>
      {children}
    </label>
  )
}

function Select({
  value,
  onChange,
  children,
}: {
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="control"
    >
      {children}
    </select>
  )
}
