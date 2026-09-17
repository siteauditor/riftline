import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import SliceFilters, { SliceSummary, type SliceValue } from '../components/SliceFilters'
import { ErrorView, Spinner } from '../components/StateViews'
import BuildPanel from '../components/champion/BuildPanel'
import LaningPanel from '../components/champion/LaningPanel'
import RunePanel from '../components/champion/RunePanel'
import PairTable from '../components/champion/PairTable'
import { api, POSITIONS, type ChampionDetail } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'

const TABS = ['Build', 'Runes', 'Laning', 'Counters', 'Synergies'] as const
type Tab = (typeof TABS)[number]

export default function Champion() {
  const { championId = '' } = useParams()
  const [search, setSearch] = useSearchParams()
  const [tab, setTab] = useState<Tab>('Build')

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
    queryFn: () => api.champion(Number(championId), slice),
    retry: false,
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

  if (query.isLoading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <Spinner label="Loading champion statistics…" />
      </div>
    )
  }
  if (query.isError) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const d: ChampionDetail = query.data!
  const o = d.overview
  const playedPositions = new Set(d.positions.map((p) => p.position))

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
        {d.champion.art_url && (
          <img
            src={d.champion.art_url}
            alt=""
            aria-hidden
            className="pointer-events-none absolute inset-0 -z-10 size-full object-cover object-[72%_18%] opacity-80"
          />
        )}
        <div className="art-scrim absolute inset-0 -z-10" />

        <div className="mx-auto flex max-w-[1280px] flex-col gap-6 px-4 pb-6 pt-20 sm:pt-32 lg:flex-row lg:items-end">
          <div className="min-w-0">
            <h1 className="display text-[clamp(2.5rem,7vw,4.25rem)] font-700 text-ink">
              {d.champion.name}
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              {d.champion.title}
              {d.champion.tags.length > 0 && (
                <span className="text-ink-faint"> &nbsp;/&nbsp; {d.champion.tags.join(', ')}</span>
              )}
            </p>
          </div>

          <dl className="flex flex-wrap items-end gap-x-7 gap-y-3 lg:ml-auto">
            <Stat label="Adjusted" value={pct(o.confidence_win_rate, 1)} accent />
            <Stat label="Win rate" value={pct(o.win_rate, 1)} />
            <Stat label="Pick" value={pct(o.pick_rate, 1)} />
            <Stat label="Ban" value={pct(o.ban_rate, 1)} />
            <Stat label="Games" value={compact(o.games)} />
            {o.tier && <Stat label="Tier" value={o.tier} accent />}
          </dl>
        </div>
      </header>

      <div className="mx-auto max-w-[1280px] px-4 py-5">
      {/* Slice controls */}
      <div className="mt-4">
        <SliceFilters
          value={{ ...slice, position: d.position }}
          onChange={updateSlice}
          positions={POSITIONS.filter((p) => playedPositions.has(p.id)).map((p) => ({
            id: p.id,
            label: p.label,
            hint: pct(d.positions.find((x) => x.position === p.id)?.share ?? 0),
          }))}
          summary={
            <SliceSummary
              patch={d.patch}
              matches={d.sample_matches}
              bracket={d.rank_bracket}
            />
          }
        />
      </div>

      {/* Averages */}
      <dl className="mt-5 grid grid-cols-3 gap-y-4 border-y border-line-soft py-3 sm:grid-cols-6">
        <Cell label="KDA" value={o.avg_kda.toFixed(2)} />
        <Cell label="K / D / A" value={`${o.avg_kills.toFixed(1)} / ${o.avg_deaths.toFixed(1)} / ${o.avg_assists.toFixed(1)}`} />
        <Cell label="CS per min" value={o.avg_cs_per_min.toFixed(1)} />
        <Cell label="Gold" value={compact(Math.round(o.avg_gold))} />
        <Cell label="Damage" value={compact(Math.round(o.avg_damage))} />
        <Cell label="Vision" value={o.avg_vision.toFixed(0)} />
      </dl>

      {/* Tabs */}
      <nav className="mt-6 flex gap-1 border-b border-line-soft text-sm">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            aria-pressed={tab === t}
            className={`-mb-px border-b-2 px-3 py-2 font-display font-600 transition-colors ${
              tab === t
                ? 'border-gold text-gold-bright'
                : 'border-transparent text-ink-dim hover:text-ink'
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="mt-5">
        {tab === 'Build' && <BuildPanel builds={d.builds} spells={d.spells} />}
        {tab === 'Runes' && <RunePanel runes={d.runes} />}
        {tab === 'Laning' && (
          <LaningPanel
            laning={d.laning}
            skills={d.skills}
            championName={d.champion.name}
          />
        )}
        {tab === 'Counters' && (
          <div className="grid gap-5 lg:grid-cols-2">
            <PairTable
              title="Hardest lane matchups"
              hint={`${d.champion.name} against the enemy ${positionLabel(d.position)}, worst first.`}
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
        {tab === 'Synergies' && (
          <PairTable
            title="Best allies"
            hint="Teammates this champion wins alongside most often, best first."
            rows={d.synergies}
            showPosition
          />
        )}
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

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-dim">{label}</dt>
      <dd
        className={`tnum display mt-0.5 text-[26px] font-700 ${
          accent ? 'text-gold-bright' : 'text-ink'
        }`}
      >
        {value}
      </dd>
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
