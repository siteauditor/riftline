import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import SliceFilters, { type SliceValue } from '../components/SliceFilters'
import { ErrorView, PageSkeleton } from '../components/StateViews'
import ItemChampions from '../components/items/ItemChampions'
import ItemSlots from '../components/items/ItemSlots'
import ItemTiming from '../components/items/ItemTiming'
import RecipeTree from '../components/items/RecipeTree'
import { points } from '../components/items/groups'
import { type ItemDetail, type ItemFigures } from '../lib/api'
import { compact, pct } from '../lib/format'
import { itemSummary } from '../lib/prose'
import { queries } from '../lib/queries'
import { sliceFromParams, sliceLink, sliceParams, withParams } from '../lib/searchParams'
import { heads } from '../lib/seo'
import CountUp from '../components/CountUp'

export default function Item() {
  const { itemId = '' } = useParams()
  const [search, setSearch] = useSearchParams()
  // Patch, queue and bracket only: an item page has no role or sample floor.
  const { patch, queueId, bracket } = sliceFromParams(search, 1)
  const slice = { patch, queueId, bracket }

  const query = useQuery({
    ...queries.item(itemId, slice),
    retry: false,
  })

  function updateSlice(next: Partial<SliceValue>) {
    const { patch, queueId, bracket } = next
    setSearch(
      (prev) =>
        withParams(prev, sliceParams({ patch, queueId, bracket }), { queue: '420', bracket: 'ALL' }),
      { replace: true },
    )
  }

  if (query.isLoading) {
    return <PageSkeleton />
  }
  if (query.isError || !query.data) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const item = query.data
  // Older links carry the id; the slug is the one address for the page.
  if (/^\d+$/.test(itemId) && item.slug) {
    const query = search.toString()
    return <Navigate to={`/items/${item.slug}${query ? `?${query}` : ''}`} replace />
  }
  const figures = item.figures
  const finished = item.group === 'finished'
  // Figures exist for items sold on the Rift and bought as themselves.
  const measurable = item.on_rift && item.group !== 'transformed'

  const summary = itemSummary(item)

  return (
    <div>
      <Head {...heads.item(item, figures?.patch)} />
      <ArtHeader>
        <div className="flex items-end gap-5">
          {item.icon_url && (
            <img
              src={item.icon_url}
              alt=""
              className="notch size-20 shrink-0 ring-1 ring-line sm:size-24" loading="lazy" decoding="async" />
          )}
          <div className="min-w-0">
            <p className="eyebrow">{item.group_label ?? (item.on_rift ? 'Item' : 'Other modes')}</p>
            <h1 className="display mt-1 text-[clamp(1.9rem,5vw,3rem)] font-800 uppercase leading-[0.95] tracking-[-0.01em] text-ink">
              {item.name}
            </h1>
            <p className="tnum mt-2 text-sm text-ink-dim">{costLine(item)}</p>
          </div>
        </div>
        {item.plaintext && (
          <p className="mt-4 max-w-prose text-sm leading-relaxed text-ink-dim">{item.plaintext}</p>
        )}
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">
        {/* The figures in sentences, from the figures themselves. */}
        {measurable && summary.length > 0 && (
          <section aria-label={`${item.name} in brief`} className="mb-6 max-w-prose space-y-2 text-sm leading-relaxed text-ink-dim">
            {summary.map((sentence, i) => (
              <p key={i} className={i === 0 ? 'text-ink' : undefined}>
                {sentence}
              </p>
            ))}
          </section>
        )}

        {measurable && (
          <SliceFilters
            value={{ ...slice, position: null, minGames: 1 }}
            onChange={updateSlice}
            hideRoles
            hideMinGames
            summary={
              figures &&
              `${compact(figures.ordered_players)} players with a timeline on patch ${figures.patch}`
            }
          />
        )}

        <div className="mt-6 grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div className="space-y-8">
            {item.stats.length > 0 && (
              <section>
                <h2 className="display text-base font-600 text-ink">What it gives</h2>
                <dl className="mt-2 border-t border-line-soft">
                  {item.stats.map((s) => (
                    <div
                      key={`${s.value}-${s.label}`}
                      className="flex items-baseline gap-3 border-b border-line-soft py-1.5"
                    >
                      <dt className="flex-1 text-sm text-ink-dim">{s.label}</dt>
                      <dd className="tnum display text-base font-700 text-ink">{s.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}

            {item.effects.length > 0 && (
              <section className="space-y-4">
                {item.effects.map((e, i) => (
                  <div key={`${e.kind}-${e.name ?? i}`}>
                    <p className="text-xs text-ink-faint">{effectLabel(e.kind)}</p>
                    {e.name && <h3 className="display text-base font-700 text-ink">{e.name}</h3>}
                    <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-ink-dim">
                      {e.text}
                    </p>
                  </div>
                ))}
              </section>
            )}

            <RecipeTree item={item} />
          </div>

          <div className="min-w-0 space-y-10">
            {figures ? (
              <>
                <Headline figures={figures} finished={finished} />
                <ItemTiming figures={figures} finished={finished} />
                <ItemSlots figures={figures} />
                <ItemChampions figures={figures} finished={finished} linkSuffix={sliceLink(slice)} />
              </>
            ) : (
              <p className="max-w-prose border-l-2 border-line pl-3 text-sm leading-relaxed text-ink-dim">
                {item.figures_note ?? 'No figures for this item yet.'}
              </p>
            )}
          </div>
        </div>

        <p className="mt-10 text-xs text-ink-faint">
          <Link to="/items" className="hover:text-ink-dim">
            Every item
          </Link>
        </p>
      </div>
    </div>
  )
}

/** The three numbers the page leads with. */
function Headline({ figures, finished }: { figures: ItemFigures; finished: boolean }) {
  if (figures.buyers === 0) {
    return (
      <p className="max-w-prose text-sm leading-relaxed text-ink-dim">
        Nobody bought this in the {compact(figures.ordered_players)} games with a timeline on
        patch {figures.patch}.
      </p>
    )
  }
  return (
    <section>
      <dl className="flex flex-wrap gap-x-10 gap-y-4">
        <Figure
          label="Bought by"
          value={pct(figures.bought_share, 1)}
          n={figures.bought_share}
          format={(n) => pct(n, 1)}
          sub={`of ${compact(figures.ordered_players)} players`}
        />
        {finished && (
          <Figure
            label="Against the same slot"
            value={figures.delta === null ? 'few games' : points(figures.delta)}
            sub={figures.delta === null ? `from ${figures.slot_min_games} purchases` : `over ${compact(figures.delta_games)} purchases`}
            color={
              figures.delta === null
                ? undefined
                : figures.delta >= 0
                  ? 'var(--color-win)'
                  : 'var(--color-loss)'
            }
          />
        )}
        <Figure
          label="Held at the end"
          value={pct(figures.held_share, 1)}
          n={figures.held_share}
          format={(n) => pct(n, 1)}
          sub={`of ${compact(figures.players)} players`}
        />
      </dl>
      {/* Finished items only: a component's buyers are nearly everyone, and
          its raw rate says nothing either way. */}
      {finished && figures.buyer_win_rate !== null && (
        <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-faint">
          Players who bought it won {pct(figures.buyer_win_rate)} of their games. That mostly
          measures how late it is bought: players who finish more items win more, from 28% with
          none to 62% with six, which is why the item is also compared with its own slot.
        </p>
      )}
    </section>
  )
}

function Figure({
  label,
  value,
  n,
  format,
  sub,
  color,
}: {
  label: string
  value: string
  /** With `format`, the figure counts up to `n` when the page is navigated to. */
  n?: number
  format?: (n: number) => string
  sub: string
  color?: string
}) {
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="tnum display mt-0.5 text-[28px] font-700 leading-none" style={{ color: color ?? 'var(--color-ink)' }}>
        {n !== undefined && format ? <CountUp value={n} format={format} /> : value}
      </dd>
      <dd className="tnum mt-1 text-xs text-ink-faint">{sub}</dd>
    </div>
  )
}

function costLine(item: ItemDetail): string {
  // A grown item carries its parent's cost in Riot's file, but the shop does
  // not sell it, and a price would say it does.
  if (!item.purchasable) return 'Not sold in the shop'
  if (!item.cost) return 'Free'
  const parts = [`${item.cost.toLocaleString('en-US')} gold`]
  if (item.builds_from.length && item.combine_cost) {
    parts.push(`${item.combine_cost.toLocaleString('en-US')} to combine`)
  }
  if (item.sell) parts.push(`sells for ${item.sell.toLocaleString('en-US')}`)
  return parts.join(', ')
}

function effectLabel(kind: string): string {
  return { passive: 'Passive', active: 'Active', unique: 'Unique', note: 'Note' }[kind] ?? kind
}
