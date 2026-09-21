import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import SliceFilters, { SliceSummary, type SliceValue } from '../components/SliceFilters'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import AbilitiesPanel from '../components/champion/AbilitiesPanel'
import BuildPanel from '../components/champion/BuildPanel'
import ChampionTabs from '../components/champion/ChampionTabs'
import LaningPanel from '../components/champion/LaningPanel'
import PairTable from '../components/champion/PairTable'
import PlayersPanel from '../components/champion/PlayersPanel'
import RunePanel from '../components/champion/RunePanel'
import SkinsPanel from '../components/champion/SkinsPanel'
import StoryPanel from '../components/champion/StoryPanel'
import { parseTab, type ChampionTab } from '../components/champion/tabs'
import { api, POSITIONS, type ChampionDetail, type PatchChange } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'

const NUMBER_TABS = new Set<ChampionTab>(['build', 'runes', 'laning', 'counters', 'synergies'])

export default function Champion() {
  const { championId = '' } = useParams()
  const id = Number(championId)
  const [search, setSearch] = useSearchParams()

  // Slice state lives in the URL so a champion page stays deep-linkable and the
  // back button behaves.
  const slice: SliceValue = {
    patch: search.get('patch'),
    queueId: Number(search.get('queue_id')) || 420,
    position: search.get('position'),
    bracket: search.get('bracket'),
    minGames: Number(search.get('min_games')) || 5,
  }

  const query = useQuery({
    queryKey: ['champion', championId, slice],
    queryFn: () => api.champion(id, slice),
    retry: false,
  })
  // Who the champion is. Its own request because the numbers above are a 404
  // on any patch where the champion has no games, and a story is not.
  const profileQuery = useQuery({
    queryKey: ['champion-profile', championId],
    queryFn: () => api.championProfile(id),
    retry: false,
    staleTime: 60 * 60 * 1000,
  })

  const d: ChampionDetail | undefined = query.data
  const profile = profileQuery.data
  // A numbers tab on a patch with no numbers would open on an error, so a page
  // without them opens on the story unless the link asked for something else.
  const tab: ChampionTab = parseTab(search.get('tab')) ?? (query.isError ? 'story' : 'build')

  const playersQuery = useQuery({
    queryKey: ['champion-players', championId],
    queryFn: () => api.championPlayers(id),
    retry: false,
    staleTime: 10 * 60 * 1000,
    enabled: tab === 'players',
  })

  const KEYS: Record<keyof SliceValue, string> = {
    patch: 'patch',
    queueId: 'queue_id',
    position: 'position',
    bracket: 'bracket',
    minGames: 'min_games',
  }

  function updateSlice(next: Partial<SliceValue>) {
    const params = new URLSearchParams(search)
    for (const [field, value] of Object.entries(next)) {
      const key = KEYS[field as keyof SliceValue]
      if (value === null || value === undefined || value === '') params.delete(key)
      else params.set(key, String(value))
    }
    setSearch(params, { replace: true })
  }

  function selectTab(next: ChampionTab) {
    const params = new URLSearchParams(search)
    params.set('tab', next)
    setSearch(params, { replace: true })
  }

  if (query.isLoading && profileQuery.isLoading) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <Spinner label="Loading champion" />
      </div>
    )
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

  const o = d?.overview
  const playedPositions = new Set(d?.positions.map((p) => p.position))

  return (
    <div>
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
            className="pointer-events-none absolute inset-0 -z-10 size-full object-cover object-[72%_18%] opacity-80"
          />
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
              <Stat label="Adjusted" value={pct(o.confidence_win_rate, 1)} accent />
              <Stat
                label="Win rate"
                value={pct(o.win_rate, 1)}
                change={change(o.win_rate, o.previous, 'win')}
              />
              <Stat
                label="Pick"
                value={pct(o.pick_rate, 1)}
                change={change(o.pick_rate, o.previous, 'pick')}
              />
              <Stat label="Ban" value={pct(o.ban_rate, 1)} />
              <Stat label="Games" value={compact(o.games)} />
              {o.tier && <Stat label="Tier" value={o.tier} accent />}
            </dl>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-[1280px] px-4 py-5">
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

        <div className="mt-5">
          {NUMBER_TABS.has(tab) && !d ? (
            query.isLoading ? (
              <Spinner label="Loading champion statistics" />
            ) : (
              <ErrorView error={query.error} onRetry={() => query.refetch()} />
            )
          ) : null}

          {d && tab === 'build' && <BuildPanel builds={d.builds} spells={d.spells} />}
          {d && tab === 'runes' && <RunePanel runes={d.runes} />}
          {d && tab === 'laning' && <LaningPanel laning={d.laning} championName={info.name} />}
          {d && tab === 'counters' && (
            <div className="grid gap-5 lg:grid-cols-2">
              <PairTable
                title="Hardest lane matchups"
                hint={`${info.name} against the enemy ${positionLabel(d.position)}, worst first.`}
                rows={d.counters.lane}
                showGold
              />
              <PairTable
                title="Hardest against the whole team"
                hint="Every enemy, not just the laner. A pick can be fine in lane and hopeless into the composition."
                rows={d.counters.team}
              />
            </div>
          )}
          {d && tab === 'synergies' && (
            <PairTable
              title="Best allies"
              hint="Teammates this champion wins alongside most often, best first."
              rows={d.synergies}
              showPosition
            />
          )}

          {tab === 'players' &&
            (playersQuery.data ? (
              <PlayersPanel board={playersQuery.data} championName={info.name} />
            ) : playersQuery.isError ? (
              <ErrorView error={playersQuery.error} onRetry={() => playersQuery.refetch()} />
            ) : (
              <Spinner label="Loading players" />
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
              <Spinner label="Loading the champion" />
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

function Stat({
  label,
  value,
  accent,
  change: moved,
}: {
  label: string
  value: string
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
        {value}
      </dd>
      {moved && (
        <dd
          className="tnum absolute left-0 top-full whitespace-nowrap text-[11px]"
          style={{ color: moved.color }}
          title={moved.title}
        >
          {moved.text}
        </dd>
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
