import { Link, Navigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import Head from '../components/Head'
import SliceFilters, { SliceSummary, type SliceValue } from '../components/SliceFilters'
import { EmptyState, ErrorView, PageSkeleton, ProseSkeleton, TableSkeleton } from '../components/StateViews'
import AbilitiesPanel from '../components/champion/AbilitiesPanel'
import BuildPanel from '../components/champion/BuildPanel'
import ChampionTabs from '../components/champion/ChampionTabs'
import LaningPanel from '../components/champion/LaningPanel'
import PairTable, { PairControls, type PairOrder } from '../components/champion/PairTable'
import PlayersPanel from '../components/champion/PlayersPanel'
import RunePanel from '../components/champion/RunePanel'
import SkinsPanel from '../components/champion/SkinsPanel'
import StoryPanel from '../components/champion/StoryPanel'
import { parseTab, type ChampionTab } from '../components/champion/tabs'
import { POSITIONS, type ChampionDetail, type ChampionRef, type PatchChange } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'
import { championSummary } from '../lib/prose'
import { CHAMPION_MIN_GAMES, queries } from '../lib/queries'
import { heads } from '../lib/seo'
import {
  SLICE_DEFAULTS,
  sliceFromParams,
  sliceLink,
  sliceParams,
  useHydratedSearchParams,
  useSearchText,
  withParams,
} from '../lib/searchParams'
import CountUp from '../components/CountUp'
import Hint from '../components/Hint'

const NUMBER_TABS = new Set<ChampionTab>(['build', 'runes', 'laning', 'counters', 'synergies'])
const MIN_GAMES = CHAMPION_MIN_GAMES

export default function Champion() {
  // A slug ("aatrox"), or an id from an older link; the API takes either.
  const { championId = '' } = useParams()
  const [search, setSearch] = useHydratedSearchParams()

  // Slice state lives in the URL so a champion page stays deep-linkable and the
  // back button behaves.
  const slice: SliceValue = sliceFromParams(search, MIN_GAMES)
  // The counters and synergies controls too, so back from an opponent's page
  // returns to the same list rather than to the top fifteen.
  const [pairQuery, setPairQuery] = useSearchText('q')
  const pairOrder: PairOrder | null =
    search.get('order') === 'best' ? 'best' : search.get('order') === 'worst' ? 'worst' : null

  const query = useQuery({
    ...queries.champion(championId, slice),
    retry: false,
  })
  // Who the champion is. Its own request because the numbers above are a 404
  // on any patch where the champion has no games, and a story is not.
  const profileQuery = useQuery({
    ...queries.championProfile(championId),
    retry: false,
    staleTime: 60 * 60 * 1000,
  })

  const d: ChampionDetail | undefined = query.data
  const profile = profileQuery.data
  // A numbers tab on a patch with no numbers would open on an error, so a page
  // without them opens on the story unless the link asked for something else.
  const tab: ChampionTab = parseTab(search.get('tab')) ?? (query.isError ? 'story' : 'build')

  const playersQuery = useQuery({
    ...queries.championPlayers(championId),
    retry: false,
    staleTime: 10 * 60 * 1000,
    enabled: tab === 'players',
  })

  function updateSlice(next: Partial<SliceValue>) {
    setSearch(
      (prev) =>
        withParams(prev, sliceParams(next), { ...SLICE_DEFAULTS, min_games: String(MIN_GAMES) }),
      { replace: true },
    )
  }

  function selectTab(next: ChampionTab) {
    // A search typed on one tab means nothing on the next.
    setSearch((prev) => withParams(prev, { tab: next, q: null, order: null }), { replace: true })
  }

  function setPairOrder(order: PairOrder, byDefault: PairOrder) {
    setSearch((prev) => withParams(prev, { order }, { order: byDefault }), { replace: true })
  }

  // Where a pair row links: the other champion on the slice being read, in
  // the lane they were in when it is known.
  const pairLink = (champion: ChampionRef, position: string | null) =>
    `/champions/${champion.slug ?? champion.id}${sliceLink({ ...slice, position })}`

  if (query.isLoading && profileQuery.isLoading) {
    return <PageSkeleton />
  }
  const info = d?.champion ?? profile?.champion
  if (!info) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <ErrorView
          error={query.error ?? profileQuery.error}
          onRetry={() => {
            query.refetch()
            profileQuery.refetch()
          }}
        />
      </div>
    )
  }

  // Older links carry the id. The slug is the address a crawler should see
  // and the one people can read, so the id form is replaced, not served twice.
  if (/^\d+$/.test(championId) && info.slug) {
    const query = search.toString()
    return <Navigate to={`/champions/${info.slug}${query ? `?${query}` : ''}`} replace />
  }

  const o = d?.overview
  const playedPositions = new Set(d?.positions.map((p) => p.position))

  return (
    <div>
      <Head {...heads.champion(info, d?.patch, d?.position, d?.overview.games)} />
      {/*
        The hero. One image per page, full strength, and the only place on the
        site where art is allowed to be the loudest thing. The scrim resolves to
        the page ground so the art appears to emerge from the page rather than
        sit in a window, and the name is set large in the condensed cut because
        a champion page is about a character before it is about a table.
      */}
      <header className="relative isolate overflow-hidden border-b border-line-soft">
        {info.art_url && (
          <img
            src={info.art_url}
            alt=""
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 size-full object-cover object-[72%_18%] opacity-80" loading="lazy" decoding="async" />
        )}
        <div className="art-scrim absolute inset-0 -z-10" />

        <div className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 pb-6 pt-20 sm:pt-32 lg:flex-row lg:items-end">
          <div className="min-w-0">
            {d && (
              <p className="eyebrow">
                {positionLabel(d.position)} · patch {d.patch}
              </p>
            )}
            <h1 className="display text-[clamp(2.5rem,7vw,4.25rem)] font-800 uppercase leading-[0.9] tracking-[-0.02em] text-ink">
              {info.name}
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              {info.title}
              {info.tags.length > 0 && (
                <span className="text-ink-faint"> &nbsp;/&nbsp; {info.tags.join(', ')}</span>
              )}
            </p>
            {d && d.positions.length > 1 && <PositionShare positions={d.positions} />}
          </div>

          {o && (
            <dl className="flex flex-wrap items-end gap-x-7 gap-y-5 lg:ml-auto">
              <Stat label="Adjusted" value={pct(o.confidence_win_rate, 1)} n={o.confidence_win_rate} format={pct1} accent />
              <Stat
                label="Win rate"
                value={pct(o.win_rate, 1)}
                n={o.win_rate}
                format={pct1}
                change={change(o.win_rate, o.previous, 'win')}
              />
              <Stat
                label="Pick"
                value={pct(o.pick_rate, 1)}
                n={o.pick_rate}
                format={pct1}
                change={change(o.pick_rate, o.previous, 'pick')}
              />
              <Stat label="Ban" value={pct(o.ban_rate, 1)} n={o.ban_rate} format={pct1} />
              <Stat label="Games" value={compact(o.games)} n={o.games} format={compact} />
              {o.tier && <Stat label="Tier" value={o.tier} accent />}
            </dl>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-[1280px] px-4 py-5">
        {/* What the numbers say, in sentences, from the numbers themselves:
            for the reader who does not know the game, and for anything that
            reads the page without clicking a tab. */}
        {d && (
          <section aria-label={`${info.name} in brief`} className="max-w-prose space-y-2 text-sm leading-relaxed text-ink-dim">
            {championSummary(d, profile).map((sentence, i) => (
              <p key={i} className={i === 0 ? 'text-ink' : undefined}>
                {sentence}
              </p>
            ))}
          </section>
        )}

        {/* Slice controls. Shown on a patch with no numbers too, because the
            way out of that page is to pick another patch. */}
        <div className="mt-4">
          <SliceFilters
            value={{ ...slice, position: d?.position ?? slice.position }}
            onChange={updateSlice}
            positions={
              d
                ? POSITIONS.filter((p) => playedPositions.has(p.id)).map((p) => ({
                    id: p.id,
                    label: p.label,
                    hint: pct(d.positions.find((x) => x.position === p.id)?.share ?? 0),
                  }))
                : undefined
            }
            summary={
              d && (
                <SliceSummary patch={d.patch} matches={d.sample_matches} bracket={d.rank_bracket} />
              )
            }
          />
        </div>

        {/* Averages */}
        {o && (
          <dl className="mt-5 grid grid-cols-3 gap-y-4 border-y border-line-soft py-3 sm:grid-cols-6">
            <Cell label="KDA" value={o.avg_kda.toFixed(2)} />
            <Cell
              label="K / D / A"
              value={`${o.avg_kills.toFixed(1)} / ${o.avg_deaths.toFixed(1)} / ${o.avg_assists.toFixed(1)}`}
            />
            <Cell label="CS per min" value={o.avg_cs_per_min.toFixed(1)} />
            <Cell label="Gold" value={compact(Math.round(o.avg_gold))} />
            <Cell label="Damage" value={compact(Math.round(o.avg_damage))} />
            <Cell label="Vision" value={o.avg_vision.toFixed(0)} />
          </dl>
        )}

        <ChampionTabs active={tab} onChange={selectTab} />

        {/* Keyed on the tab, so each section fades in as it replaces the last. */}
        <div key={tab} id="champion-tabpanel" role="tabpanel" className="mt-5 animate-in fade-in-0 duration-200">
          {NUMBER_TABS.has(tab) && !d ? (
            query.isLoading ? (
              <TableSkeleton rows={6} />
            ) : (
              <ErrorView error={query.error} onRetry={() => query.refetch()} />
            )
          ) : null}

          {d && tab === 'build' && (
            <BuildPanel
              builds={d.builds}
              spells={d.spells}
              itemSearch={sliceLink({ patch: slice.patch, queueId: slice.queueId, bracket: slice.bracket })}
            />
          )}
          {d && tab === 'runes' && <RunePanel runes={d.runes} />}
          {d && tab === 'laning' && <LaningPanel laning={d.laning} championName={info.name} />}
          {d && tab === 'counters' && (
            <>
              <PairControls
                query={pairQuery}
                onQuery={setPairQuery}
                order={pairOrder ?? 'worst'}
                onOrder={(o) => setPairOrder(o, 'worst')}
                worstLabel="Hardest first"
                bestLabel="Easiest first"
                placeholder="Find an opponent"
              />
              <div className="grid gap-5 lg:grid-cols-2">
                <PairTable
                  title={pairOrder === 'best' ? 'Easiest lane matchups' : 'Hardest lane matchups'}
                  hint={`${info.name} against the enemy ${positionLabel(d.position)}, ${
                    pairOrder === 'best' ? 'best' : 'worst'
                  } first.`}
                  rows={d.counters.lane}
                  order={pairOrder ?? 'worst'}
                  query={pairQuery}
                  showGold
                  linkFor={(row) => pairLink(row.champion, d.position)}
                />
                <PairTable
                  title={
                    pairOrder === 'best'
                      ? 'Easiest against the whole team'
                      : 'Hardest against the whole team'
                  }
                  hint="Every enemy, not just the laner. A pick can be fine in lane and hopeless into the composition."
                  rows={d.counters.team}
                  order={pairOrder ?? 'worst'}
                  query={pairQuery}
                  linkFor={(row) => pairLink(row.champion, null)}
                />
              </div>
            </>
          )}
          {d && tab === 'synergies' && (
            <>
              <PairControls
                query={pairQuery}
                onQuery={setPairQuery}
                order={pairOrder ?? 'best'}
                onOrder={(o) => setPairOrder(o, 'best')}
                worstLabel="Worst first"
                bestLabel="Best first"
                placeholder="Find an ally"
              />
              <PairTable
                title={pairOrder === 'worst' ? 'Worst allies' : 'Best allies'}
                hint={`Teammates this champion wins alongside ${
                  pairOrder === 'worst' ? 'least' : 'most'
                } often, ${pairOrder === 'worst' ? 'worst' : 'best'} first.`}
                rows={d.synergies}
                order={pairOrder ?? 'best'}
                query={pairQuery}
                showPosition
                linkFor={(row) => pairLink(row.champion, row.position)}
              />
            </>
          )}

          {tab === 'players' &&
            (playersQuery.data ? (
              <PlayersPanel board={playersQuery.data} championName={info.name} />
            ) : playersQuery.isError ? (
              <ErrorView error={playersQuery.error} onRetry={() => playersQuery.refetch()} />
            ) : (
              <TableSkeleton rows={8} />
            ))}

          {(tab === 'story' || tab === 'abilities' || tab === 'skins') &&
            (profile ? (
              <>
                {tab === 'story' && <StoryPanel profile={profile} />}
                {tab === 'abilities' && (
                  <AbilitiesPanel
                    passive={profile.passive}
                    abilities={profile.abilities}
                    skills={d?.skills}
                    slice={d && { patch: d.patch, position: d.position }}
                    championName={info.name}
                  />
                )}
                {tab === 'skins' && (
                  <SkinsPanel profile={profile} initial={Number(search.get('skin')) || null} />
                )}
              </>
            ) : profileQuery.isError ? (
              <ErrorView error={profileQuery.error} onRetry={() => profileQuery.refetch()} />
            ) : profileQuery.isLoading ? (
              <ProseSkeleton />
            ) : (
              <EmptyState title="Nothing to show" body="This champion has no profile yet." />
            ))}
        </div>

        <p className="mt-8 text-xs text-ink-faint">
          <Link to="/tierlist" className="hover:text-ink-dim">
            Back to the tier list
          </Link>
        </p>
      </div>
    </div>
  )
}

/**
 * The move since the patch before, only where it is real: the two 95%
 * intervals no longer overlap. Measured on 16.17 to 16.18, 293 of 760 win
 * rates moved 20 points or more and 2 of those moves passed, so an unmarked
 * figure is the ordinary case, not a gap.
 */
function change(
  now: number,
  previous: PatchChange | null | undefined,
  kind: 'win' | 'pick',
): Change | undefined {
  if (!previous) return undefined
  const moved = kind === 'win' ? previous.win_rate_moved : previous.pick_rate_moved
  if (!moved) return undefined
  const before = kind === 'win' ? previous.win_rate : previous.pick_rate
  const points = (now - before) * 100
  return {
    text: `${points >= 0 ? '+' : ''}${points.toFixed(1)} since ${previous.patch}`,
    // Only a win rate has a good direction. A pick rate going up is a fact
    // about the meta, not a verdict on the champion, so it stays neutral.
    color:
      kind === 'win'
        ? points >= 0
          ? 'var(--color-win)'
          : 'var(--color-loss)'
        : 'var(--color-ink-dim)',
    title: `${kind === 'win' ? 'Win rate' : 'Pick rate'} on ${previous.patch} was ${pct(before, 1)} over ${compact(previous.games)} games, and the two ranges no longer overlap.`,
  }
}

interface Change {
  text: string
  color: string
  title: string
}

const pct1 = (n: number) => pct(n, 1)

function Stat({
  label,
  value,
  n,
  format,
  accent,
  change: moved,
}: {
  label: string
  value: string
  /** With `format`, the figure counts up to `n` when the page is navigated to. */
  n?: number
  format?: (n: number) => string
  accent?: boolean
  change?: Change
}) {
  return (
    // Relative, so a change note hangs below the figure instead of pushing it
    // up: the row is bottom aligned, and one taller cell lifted its number
    // above every other number in the row.
    <div className="relative">
      <dt className="text-[11px] text-ink-dim">{label}</dt>
      <dd
        className={`tnum display mt-0.5 text-[26px] font-700 ${
          accent ? 'text-gold-bright' : 'text-ink'
        }`}
      >
        {n !== undefined && format ? <CountUp value={n} format={format} /> : value}
      </dd>
      {moved && (
        <Hint text={moved.title}>
          <dd
            tabIndex={0}
            className="tnum absolute left-0 top-full whitespace-nowrap text-[11px] outline-none"
            style={{ color: moved.color }}
          >
            {moved.text}
          </dd>
        </Hint>
      )}
    </div>
  )
}

function Cell({ label, value }: { label: string; value: string }) {
  // A divider, not a box. Six identical cards in a row was the single clearest
  // symptom of the card kit this redesign is removing: the figures are one set
  // of related numbers, so they read as one band with rules between them.
  return (
    <div className="sm:border-l sm:border-line sm:px-3 sm:first:border-l-0 sm:first:pl-0">
      <dt className="text-[11px] text-ink-faint">{label}</dt>
      <dd className="tnum display mt-0.5 text-lg font-600 text-ink">{value}</dd>
    </div>
  )
}

/**
 * Where the champion is played, as one bar. The role filter below carries the
 * same shares as hints on its buttons; this is the picture of them.
 */
function PositionShare({ positions }: { positions: ChampionDetail['positions'] }) {
  const shown = positions.filter((p) => p.share >= 0.02)
  return (
    <div className="mt-3 max-w-sm">
      <div className="flex h-1.5 gap-px overflow-hidden bg-raised" aria-hidden>
        {shown.map((p, i) => (
          <span
            key={p.position}
            className={i === 0 ? 'bg-ink-dim' : 'bg-ink-faint/50'}
            style={{ width: `${p.share * 100}%` }}
          />
        ))}
      </div>
      <p className="tnum mt-1 text-xs text-ink-dim">
        {shown.map((p) => `${positionLabel(p.position)} ${pct(p.share)}`).join(', ')}
      </p>
    </div>
  )
}
