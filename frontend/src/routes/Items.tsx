import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import { ErrorView, Spinner } from '../components/StateViews'
import { matchesFilter, STAT_FILTERS, type StatFilterKey } from '../components/items/groups'
import { api, type ItemSummary } from '../lib/api'
import { pct } from '../lib/format'
import { useDebounced } from '../lib/useDebounced'

/**
 * Every item sold on Summoner's Rift, in the sections a player thinks in.
 *
 * Built from Riot's item file, with the copies Riot keeps for other modes left
 * out: 33 of its 138 "finished items" never appear in a ranked game. Finished
 * items are ordered by how often they are bought, which is the question the
 * list is opened with.
 */
export default function Items() {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<StatFilterKey | null>(null)
  const needle = useDebounced(query, 120).trim().toLowerCase()

  const list = useQuery({ queryKey: ['items'], queryFn: api.items, staleTime: 10 * 60 * 1000 })

  const sections = useMemo(
    () =>
      (list.data?.sections ?? []).map((s) => ({
        ...s,
        shown: s.items.filter((i) => matchesFilter(i, filter, needle)),
      })),
    [list.data, filter, needle],
  )
  const total = sections.reduce((n, s) => n + s.items.length, 0)
  const shown = sections.reduce((n, s) => n + s.shown.length, 0)

  return (
    <div>
      <ArtHeader>
        <p className="eyebrow">
          {list.data?.patch ? `Patch ${list.data.patch}, ranked solo` : "Summoner's Rift"}
        </p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Items
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          Everything sold on Summoner's Rift: what it gives, what it is built from, who buys
          it and when. Open an item to see how it does against the other items bought at the
          same point in a game.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line-soft pb-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-xs text-ink-faint">Find</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type an item name"
              className="control h-8 w-52 text-sm placeholder:text-ink-faint"
            />
          </label>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by what an item gives">
            {STAT_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(filter === f.key ? null : f.key)}
                className={`border px-2 py-0.5 text-xs transition-colors ${
                  filter === f.key
                    ? 'border-gold text-gold-bright'
                    : 'border-line text-ink-dim hover:text-ink'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          {list.data && (
            <span className="tnum ml-auto text-xs text-ink-faint">
              {shown === total ? `${total} items` : `${shown} of ${total} shown`}
            </span>
          )}
        </div>

        {list.isLoading ? (
          <div className="py-10">
            <Spinner label="Loading items" />
          </div>
        ) : list.isError ? (
          <div className="mt-6">
            <ErrorView error={list.error} onRetry={() => list.refetch()} />
          </div>
        ) : shown === 0 ? (
          <p className="mt-6 text-sm text-ink-faint">
            No item matches that.{' '}
            <button
              type="button"
              onClick={() => {
                setQuery('')
                setFilter(null)
              }}
              className="underline decoration-line underline-offset-2 hover:text-gold-bright"
            >
              Clear it
            </button>
          </p>
        ) : (
          <div className="mt-6 space-y-9">
            {sections
              .filter((s) => s.shown.length > 0)
              .map((s) => (
                <section key={s.key} aria-labelledby={`items-${s.key}`}>
                  <div className="mb-3 flex items-baseline gap-3">
                    <h2 id={`items-${s.key}`} className="display text-xl font-700 text-ink">
                      {s.label}
                    </h2>
                    <span className="tnum text-xs text-ink-faint">{s.shown.length}</span>
                  </div>
                  <ul className="grid grid-cols-[repeat(auto-fill,minmax(17rem,1fr))] gap-x-3 gap-y-1">
                    {s.shown.map((item) => (
                      <ItemCard key={item.id} item={item} showShare={s.key === 'finished'} />
                    ))}
                  </ul>
                </section>
              ))}
          </div>
        )}
      </div>
    </div>
  )
}

function ItemCard({ item, showShare }: { item: ItemSummary; showShare: boolean }) {
  return (
    <li>
      <Link
        to={`/items/${item.id}`}
        className="lift group flex items-center gap-3 px-2 py-2"
        title={item.plaintext || undefined}
      >
        {item.icon_url ? (
          <img
            src={item.icon_url}
            alt=""
            loading="lazy"
            className="size-10 shrink-0 ring-1 ring-line transition-[box-shadow] group-hover:ring-gold"
          />
        ) : (
          <span className="size-10 shrink-0 bg-raised" />
        )}
        <span className="min-w-0 flex-1">
          <span className="display block truncate text-[15px] font-600 text-ink group-hover:text-gold-bright">
            {item.name}
          </span>
          <span className="tnum block truncate text-xs text-ink-faint">
            {item.cost ? `${item.cost.toLocaleString('en-US')} gold` : 'Free'}
            {item.stats[0] && `, ${item.stats[0].value} ${item.stats[0].label}`}
          </span>
        </span>
        {showShare && item.bought_share !== null && (
          <span
            className="tnum shrink-0 text-right text-xs text-ink-dim"
            title="Share of players who bought it, on the newest patch"
          >
            {pct(item.bought_share, 1)}
          </span>
        )}
      </Link>
    </li>
  )
}
