import { useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ProfileTabs from '../components/ProfileTabs'
import { ErrorView, Spinner } from '../components/StateViews'
import { api, type ChampionStatic, type MasteryEntry } from '../lib/api'
import { compact, pct, timeAgo } from '../lib/format'

/**
 * Mastery level -> colour.
 *
 * A sequential ramp, because mastery is a progression: cool and dim for
 * untouched champions, warming to gold at the top. Unplayed champions are drawn
 * too -- the gaps in a pool are the interesting part of the picture.
 */
function levelColor(level: number): string {
  if (level <= 0) return 'var(--color-line)'
  if (level < 4) return '#3a4a63'
  // Darkened from #4b6fa8, which left the level number on it at 4.35:1 with
  // light ink and 3.75:1 with dark: a step that no text colour could clear.
  if (level < 6) return '#45659c'
  if (level < 7) return 'var(--color-win)'
  if (level < 8) return 'var(--color-platinum)'
  if (level < 10) return 'var(--color-gold)'
  return 'var(--color-gold-bright)'
}

/**
 * Ink for the level number, which sits on `levelColor`.
 *
 * The ramp crosses from dark blues to a light teal and gold halfway up, so one
 * text colour cannot serve all of it: dark ink on the level-3 blue measured
 * 2.12:1, across 57 badges.
 */
function levelInk(level: number): string {
  return level < 6 ? 'var(--color-ink)' : 'var(--color-deep)'
}

type SortKey = 'points' | 'level' | 'recent' | 'name'

const SORTS: { key: SortKey; label: string }[] = [
  { key: 'points', label: 'Points' },
  { key: 'level', label: 'Level' },
  { key: 'recent', label: 'Recently played' },
  { key: 'name', label: 'Name' },
]

const ROLES = ['All', 'Fighter', 'Tank', 'Mage', 'Assassin', 'Marksman', 'Support']

interface Cell {
  id: number
  name: string
  icon: string | null
  tags: string[]
  level: number
  points: number
  lastPlayed: number | null
  entry: MasteryEntry | null
}

export default function Mastery() {
  const { platform = '', name = '', tag = '' } = useParams()
  const [sort, setSort] = useState<SortKey>('points')
  const [role, setRole] = useState('All')
  const [showUnplayed, setShowUnplayed] = useState(true)
  const [selected, setSelected] = useState<Cell | null>(null)

  const masteryQuery = useQuery({
    queryKey: ['mastery', platform, name, tag],
    queryFn: () => api.mastery(platform, name, tag),
  })

  const championsQuery = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })

  const cells = useMemo<Cell[]>(() => {
    const champions: ChampionStatic[] = championsQuery.data?.champions ?? []
    const byId = new Map(masteryQuery.data?.entries.map((e) => [e.champion.id, e]) ?? [])
    return champions.map((c) => {
      const entry = byId.get(c.id) ?? null
      return {
        id: c.id,
        name: c.name,
        icon: c.icon_url,
        tags: c.tags,
        level: entry?.level ?? 0,
        points: entry?.points ?? 0,
        lastPlayed: entry?.last_play_time ?? null,
        entry,
      }
    })
  }, [championsQuery.data, masteryQuery.data])

  const visible = useMemo(() => {
    let list = cells
    if (role !== 'All') list = list.filter((c) => c.tags.includes(role))
    if (!showUnplayed) list = list.filter((c) => c.points > 0)
    const sorted = [...list]
    sorted.sort((a, b) => {
      switch (sort) {
        case 'level':
          return b.level - a.level || b.points - a.points
        case 'recent':
          return (b.lastPlayed ?? 0) - (a.lastPlayed ?? 0)
        case 'name':
          return a.name.localeCompare(b.name)
        default:
          return b.points - a.points
      }
    })
    return sorted
  }, [cells, role, showUnplayed, sort])

  if (masteryQuery.isLoading || championsQuery.isLoading) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <Spinner label="Loading champion mastery…" />
      </div>
    )
  }

  if (masteryQuery.isError) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-10">
        <ErrorView
          error={masteryQuery.error}
          context={`${name}#${tag}`}
          onRetry={() => masteryQuery.refetch()}
        />
      </div>
    )
  }

  const mastery = masteryQuery.data!
  const totalChampions = cells.length || 1
  const played = cells.filter((c) => c.points > 0).length

  return (
    <div className="mx-auto max-w-[1280px] px-4 py-6">
      <header className="flex flex-wrap items-center gap-4 border-b border-line-soft pb-5">
        <div>
          <h1 className="display text-[clamp(1.9rem,4vw,2.6rem)] font-700 text-ink">
            {name}
            <span className="ml-1.5 text-lg font-600 text-ink-faint">#{tag}</span>
          </h1>
          <p className="mt-0.5 text-sm text-ink-dim">Champion mastery</p>
        </div>
        <ProfileTabs platform={platform} name={name} tag={tag} />
      </header>

      {/* Summary */}
      <div className="mt-5 grid grid-cols-2 gap-y-4 sm:grid-cols-3">
        <Stat label="Mastery points" value={compact(mastery.total_points)} />
        <Stat
          label="Champions played"
          value={`${played}`}
          sub={`of ${totalChampions}, ${pct(played / totalChampions)}`}
        />
        <Stat
          label="Deepest pool"
          value={`${cells.filter((c) => c.level >= 7).length}`}
          sub="at level 7 or above"
        />
      </div>

      {/* Controls */}
      <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-3 border-y border-line-soft py-3 text-sm">
        <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
          <span className="mr-1 text-xs text-ink-faint">Sort</span>
          {SORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              aria-pressed={sort === s.key}
              className={`border-b-2 px-2.5 pb-1.5 pt-1 font-display font-600 transition-colors ${
                sort === s.key
                  ? 'border-gold text-gold-bright'
                  : 'border-transparent text-ink-dim hover:text-ink'
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
          <span className="mr-1 text-xs text-ink-faint">Role</span>
          {ROLES.map((r) => (
            <button
              key={r}
              onClick={() => setRole(r)}
              aria-pressed={role === r}
              className={`border-b-2 px-2.5 pb-1.5 pt-1 font-display font-600 transition-colors ${
                role === r
                  ? 'border-gold text-gold-bright'
                  : 'border-transparent text-ink-dim hover:text-ink'
              }`}
            >
              {r}
            </button>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-ink-dim">
          <input
            type="checkbox"
            checked={showUnplayed}
            onChange={(e) => setShowUnplayed(e.target.checked)}
            className="size-3.5 accent-[var(--color-gold)]"
          />
          Show unplayed
        </label>

        <span className="ml-auto text-xs text-ink-faint">
          {visible.length} champions
        </span>
      </div>

      {/* The grid: the whole pool, gaps included */}
      <div className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(52px,1fr))] gap-1.5">
        {visible.map((c) => (
          <button
            key={c.id}
            onClick={() => setSelected(c)}
            title={`${c.name}, ${c.points ? `${compact(c.points)} pts, level ${c.level}` : 'never played'}`}
            className="group relative aspect-square overflow-hidden rounded-sm transition-transform hover:z-10 hover:scale-110"
            style={{ boxShadow: `inset 0 0 0 2px ${levelColor(c.level)}` }}
          >
            {c.icon && (
              <img
                src={c.icon}
                alt={c.name}
                loading="lazy"
                className="size-full object-cover transition-[filter,opacity]"
                style={{
                  filter: c.points ? 'none' : 'grayscale(1)',
                  opacity: c.points ? 1 : 0.35,
                }}
              />
            )}
            {c.level > 0 && (
              <span
                className="tnum absolute bottom-0 right-0 px-1 text-[10px] font-700 leading-tight"
                style={{ background: levelColor(c.level), color: levelInk(c.level) }}
              >
                {c.level}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Legend */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-faint">
        <span>Mastery level</span>
        {[0, 3, 5, 6, 7, 9, 10].map((l) => (
          <span key={l} className="flex items-center gap-1.5">
            <span
              className="size-3 rounded-sm"
              style={{ background: levelColor(l) }}
              aria-hidden
            />
            {l === 0 ? 'Unplayed' : l === 10 ? '10+' : l}
          </span>
        ))}
      </div>

      {selected && <ChampionDetail cell={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  // Rules, not boxes. Three identical cards in a row is the card kit, and these
  // are one set of related figures rather than three separate objects.
  return (
    <div className="sm:border-l sm:border-line sm:px-4 sm:first:border-l-0 sm:first:pl-0">
      <p className="text-[11px] text-ink-faint">{label}</p>
      <p className="tnum display mt-0.5 text-[28px] font-700 text-ink">{value}</p>
      {sub && <p className="tnum mt-0.5 text-xs text-ink-faint">{sub}</p>}
    </div>
  )
}

function ChampionDetail({ cell, onClose }: { cell: Cell; onClose: () => void }) {
  const e = cell.entry
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-50 border-t border-line bg-panel px-4 py-3 shadow-[0_-8px_24px_rgba(0,0,0,0.4)]"
      role="dialog"
      aria-label={`${cell.name} mastery detail`}
    >
      <div className="mx-auto flex max-w-[1280px] items-center gap-4">
        {cell.icon && (
          <img
            src={cell.icon}
            alt=""
            className="size-12 rounded-sm"
            style={{ boxShadow: `inset 0 0 0 2px ${levelColor(cell.level)}` }}
          />
        )}
        <div className="min-w-0">
          <p className="font-display text-base font-700 text-ink">{cell.name}</p>
          <p className="text-xs text-ink-dim">{cell.tags.join(', ') || '–'}</p>
        </div>

        {e ? (
          <dl className="ml-auto flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
            <Pair label="Level" value={String(e.level)} />
            <Pair label="Points" value={compact(e.points)} />
            {e.points_until_next_level > 0 && (
              <Pair label="To next" value={compact(e.points_until_next_level)} />
            )}
            {e.last_play_time && (
              <Pair label="Last played" value={timeAgo(e.last_play_time)} />
            )}
          </dl>
        ) : (
          <p className="ml-auto text-sm text-ink-faint">Never played</p>
        )}

        <button
          onClick={onClose}
          className="ml-2 rounded-sm border border-line px-2.5 py-1 text-sm text-ink-dim hover:border-gold hover:text-gold-bright"
        >
          Close
        </button>
      </div>
    </div>
  )
}

function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="tnum font-600 text-ink">{value}</dd>
    </div>
  )
}
