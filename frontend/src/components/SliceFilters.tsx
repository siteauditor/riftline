import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Chip, ChipGroup, ChipLink } from '@/components/ui/chips'

import PositionIcon from './PositionIcon'
import SelectField from './SelectField'
import { api, POSITIONS } from '../lib/api'
import { compact } from '../lib/format'
import { minGamesOptions } from '../lib/minGames'

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
  /**
   * Where each role's page is, for a page whose roles are pages (a champion's):
   * the role row is then links rather than buttons, and `onChange` never
   * carries a role.
   */
  roleLink?: (position: string) => string
}

const QUEUES = [
  { id: 420, label: 'Solo/Duo' },
  { id: 440, label: 'Flex' },
]

// The "no patch" choice needs a word: Radix refuses an empty item value.
const LATEST = 'latest'

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
  roleLink,
}: Props) {
  const { data: corpus } = useQuery({ queryKey: ['corpus'], queryFn: api.corpus })

  const patches = [...new Set((corpus?.slices ?? []).map((s) => s.patch))].filter(Boolean)
  const brackets = corpus?.brackets ?? []
  const roles: { id: string; label: string; hint?: string }[] =
    positions ?? POSITIONS.map((p) => ({ id: p.id as string, label: p.label as string }))

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line-soft pb-3 text-sm">
      {!hideRoles && (
        <ChipGroup label="Role" className="gap-x-1 gap-y-1">
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
          {roles.map((role) => {
            const inside = (
              <>
                <PositionIcon position={role.id} className="size-4" />
                {role.label}
                {role.hint && <span className="tnum ml-0.5 text-xs text-ink-faint">{role.hint}</span>}
              </>
            )
            return roleLink ? (
              <ChipLink key={role.id} to={roleLink(role.id)} active={value.position === role.id}>
                {inside}
              </ChipLink>
            ) : (
              <Chip key={role.id} active={value.position === role.id} onClick={() => onChange({ position: role.id })}>
                {inside}
              </Chip>
            )
          })}
        </ChipGroup>
      )}

      {patches.length > 1 && (
        <SelectField
          label="Patch"
          value={value.patch ?? LATEST}
          onValueChange={(v) => onChange({ patch: v === LATEST ? null : v })}
          options={[{ value: LATEST, label: 'Latest' }, ...patches.map((p) => ({ value: p, label: p }))]}
        />
      )}

      <SelectField
        label="Queue"
        value={String(value.queueId)}
        onValueChange={(v) => onChange({ queueId: Number(v) })}
        options={QUEUES.map((q) => ({ value: String(q.id), label: q.label }))}
      />

      {!hideBracket && brackets.length > 1 && (
        <SelectField
          label="Crawled from"
          value={value.bracket ?? 'ALL'}
          onValueChange={(v) => onChange({ bracket: v })}
          options={brackets.map((b) => ({
            value: b,
            label: b === 'ALL' ? 'Everything' : b.charAt(0) + b.slice(1).toLowerCase(),
          }))}
        />
      )}

      {/* The draft's presets rather than a number box. The box held what was
          typed and set the floor once typing paused, which was a request per
          pause and a floor nobody else offers (a link with min_games=7 still
          works: its own number joins the list). */}
      {!hideMinGames && (
        <SelectField
          label="Min games"
          value={String(value.minGames)}
          onValueChange={(v) => onChange({ minGames: Number(v) })}
          options={minGamesOptions(value.minGames)}
        />
      )}

      {summary && <span className="ml-auto text-xs text-ink-faint">{summary}</span>}
    </div>
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
