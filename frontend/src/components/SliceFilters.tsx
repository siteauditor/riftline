import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import PositionIcon from './PositionIcon'
import { api, POSITIONS } from '../lib/api'
import { compact } from '../lib/format'

export interface SliceValue {
  patch: string | null
  queueId: number
  position: string | null
  bracket: string | null
  minGames: number
}

interface Props {
  value: SliceValue
  onChange: (next: Partial<SliceValue>) => void
  /** Roles to offer. Omit for all five plus "All"; pass a subset on a champion page. */
  positions?: { id: string; label: string; hint?: string }[]
  allowAllPositions?: boolean
  /** Rendered on the right, e.g. "1.1k matches on patch 16.18". */
  summary?: ReactNode
  /**
   * Leave out "Crawled from". It is where the crawler started, not a rank: on
   * 16.18 Challenger was 1,403 of 1,593 games, so it barely filters. The tier
   * list says how its games were really ranked instead.
   */
  hideBracket?: boolean
  /** Leave out the role row, for a page that is not about one role (an item). */
  hideRoles?: boolean
  /** Leave out "Min games", for a page whose floors are its own. */
  hideMinGames?: boolean
}

const QUEUES = [
  { id: 420, label: 'Solo/Duo' },
  { id: 440, label: 'Flex' },
]

/**
 * The slice every aggregate is keyed by: patch, queue, role, bracket, sample floor.
 *
 * Shared by the tier list and the champion page so the two never drift apart.
 * Patch and bracket options come from `/api/meta/corpus`, which reports what has
 * actually been ingested, rather than a hardcoded list that would offer slices
 * with no data behind them.
 */
export default function SliceFilters({
  value,
  onChange,
  positions,
  allowAllPositions = false,
  summary,
  hideBracket = false,
  hideRoles = false,
  hideMinGames = false,
}: Props) {
  const { data: corpus } = useQuery({ queryKey: ['corpus'], queryFn: api.corpus })

  const patches = [...new Set((corpus?.slices ?? []).map((s) => s.patch))].filter(Boolean)
  const brackets = corpus?.brackets ?? []
  const roles: { id: string; label: string; hint?: string }[] =
    positions ?? POSITIONS.map((p) => ({ id: p.id as string, label: p.label as string }))

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line-soft pb-3 text-sm">
      {!hideRoles && (
        <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
          <span className="mr-1 text-xs text-ink-faint">Role</span>
          {allowAllPositions && (
            <Chip
              active={value.position === null}
              onClick={() => onChange({ position: null })}
            >
              <PositionIcon position="ALL" className="size-4" />
              All
            </Chip>
          )}
          {roles.map((role) => (
            <Chip
              key={role.id}
              active={value.position === role.id}
              onClick={() => onChange({ position: role.id })}
            >
              <PositionIcon position={role.id} className="size-4" />
              {role.label}
              {role.hint && (
                <span className="tnum ml-0.5 text-xs text-ink-faint">{role.hint}</span>
              )}
            </Chip>
          ))}
        </div>
      )}

      {patches.length > 1 && (
        <Select
          label="Patch"
          value={value.patch ?? ''}
          onChange={(v) => onChange({ patch: v || null })}
          options={[{ value: '', label: 'Latest' }, ...patches.map((p) => ({ value: p, label: p }))]}
        />
      )}

      <Select
        label="Queue"
        value={String(value.queueId)}
        onChange={(v) => onChange({ queueId: Number(v) })}
        options={QUEUES.map((q) => ({ value: String(q.id), label: q.label }))}
      />

      {!hideBracket && brackets.length > 1 && (
        <Select
          label="Crawled from"
          title="Which ladder the crawler was seeded from. Not a measured lobby rank."
          value={value.bracket ?? 'ALL'}
          onChange={(v) => onChange({ bracket: v })}
          options={brackets.map((b) => ({
            value: b,
            label: b === 'ALL' ? 'Everything' : b.charAt(0) + b.slice(1).toLowerCase(),
          }))}
        />
      )}

      {!hideMinGames && (
        <label className="flex items-center gap-2 text-ink-dim">
          <span className="text-xs text-ink-faint">Min games</span>
          <input
            type="number"
            min={1}
            value={value.minGames}
            onChange={(e) => onChange({ minGames: Math.max(1, Number(e.target.value) || 1) })}
            className="control tnum w-16"
          />
        </label>
      )}

      {summary && <span className="ml-auto text-xs text-ink-faint">{summary}</span>}
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-1.5 border-b-2 px-2.5 pb-1.5 pt-1 font-display font-600 transition-colors ${
        active
          ? 'border-gold text-gold-bright'
          : 'border-transparent text-ink-dim hover:text-ink'
      }`}
    >
      {children}
    </button>
  )
}

function Select({
  label,
  value,
  onChange,
  options,
  title,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: { value: string; label: string }[]
  title?: string
}) {
  return (
    <label className="flex items-center gap-2 text-ink-dim" title={title}>
      <span className="text-xs text-ink-faint">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="control"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  )
}

/** Shared right-hand summary so both pages phrase the sample the same way. */
export function SliceSummary({
  patch,
  matches,
  bracket,
}: {
  patch: string
  matches: number
  bracket?: string
}) {
  return (
    <>
      {compact(matches)} matches on patch {patch}
      {bracket && bracket !== 'ALL' && `, crawled from ${bracket.toLowerCase()}`}
    </>
  )
}
