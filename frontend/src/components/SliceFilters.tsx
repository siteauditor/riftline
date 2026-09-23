import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Chip, ChipGroup, ChipLink } from '@/components/ui/chips'

import PositionIcon from './PositionIcon'
import SelectField from './SelectField'
import { api, POSITIONS } from '../lib/api'
import { compact } from '../lib/format'
import { useDebounced } from '../lib/useDebounced'

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

      {!hideMinGames && (
        <MinGames value={value.minGames} onChange={(minGames) => onChange({ minGames })} />
      )}

      {summary && <span className="ml-auto text-xs text-ink-faint">{summary}</span>}
    </div>
  )
}

/**
 * The sample floor, typed.
 *
 * It was bound straight to the slice and clamped on every keystroke, so
 * clearing the box snapped it to 1 and typing 50 then read 150 (reproduced on
 * the live tier list), and each digit was a request. The box now holds what is
 * typed, empty included, and the floor changes on Enter, on leaving the box, or
 * once typing pauses.
 */
function MinGames({ value, onChange }: { value: number; onChange: (value: number) => void }) {
  const [draft, setDraft] = useState(String(value))
  const settled = useDebounced(draft, 500)
  // Read by the settle below, which must run when the draft settles and not
  // again when the floor it just set comes back as a new `value`.
  const current = useRef({ value, onChange })

  useEffect(() => {
    current.current = { value, onChange }
  })

  // Follow a change from outside: the back button, or a link with its own floor.
  const [followed, setFollowed] = useState(value)
  if (followed !== value) {
    setFollowed(value)
    setDraft(String(value))
  }

  const commit = (text: string, restore: boolean) => {
    const n = Math.floor(Number(text))
    if (text.trim() !== '' && Number.isFinite(n) && n >= 1) {
      if (n !== current.current.value) current.current.onChange(n)
    } else if (restore) {
      setDraft(String(current.current.value))
    }
  }

  useEffect(() => {
    const n = Math.floor(Number(settled))
    const { value: floor, onChange: set } = current.current
    if (settled.trim() !== '' && Number.isFinite(n) && n >= 1 && n !== floor) set(n)
  }, [settled])

  return (
    <label className="flex items-center gap-2 text-ink-dim">
      <span className="text-xs text-ink-faint">Min games</span>
      <input
        type="number"
        inputMode="numeric"
        min={1}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => commit(draft, true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit(draft, true)
        }}
        className="control tnum w-16"
      />
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
