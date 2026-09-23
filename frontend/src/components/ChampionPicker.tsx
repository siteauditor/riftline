import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'

import { api, type ChampionStatic } from '../lib/api'

interface Props {
  value: number | null
  onChange: (id: number | null) => void
  label: string
  placeholder?: string
}

/**
 * Searchable champion select.
 *
 * Typing is the fast path -- 173 champions is far too many to scan visually --
 * so the field filters as you type and Enter takes the first match.
 */
export default function ChampionPicker({ value, onChange, label, placeholder }: Props) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const { data } = useQuery({
    queryKey: ['champions'],
    queryFn: api.champions,
    staleTime: 6 * 60 * 60 * 1000,
  })

  // Depend on `data?.champions` directly, not on a `?? []` fallback: the
  // fallback allocates a new array every render and defeats the memo.
  const champions = data?.champions
  const selected = champions?.find((c) => c.id === value) ?? null

  const matches = useMemo(() => {
    const list: ChampionStatic[] = champions ?? []
    const q = query.trim().toLowerCase()
    if (!q) return list.slice(0, 40)
    return list.filter((c) => c.name.toLowerCase().includes(q)).slice(0, 40)
  }, [champions, query])

  function choose(id: number | null) {
    onChange(id)
    setQuery('')
    setOpen(false)
  }

  const showList = open && !selected && matches.length > 0

  return (
    <div>
      <span className="mb-1 block text-xs text-ink-faint">{label}</span>

      {selected ? (
        <div className="flex h-10 items-center gap-2 frame px-2">
          {selected.icon_url && (
            <img src={selected.icon_url} alt="" className="size-7 rounded-sm" loading="lazy" decoding="async" />
          )}
          <span className="flex-1 truncate text-sm text-ink">{selected.name}</span>
          <button
            onClick={() => choose(null)}
            aria-label={`Clear ${label}`}
            className="rounded-sm px-2 text-sm text-ink-faint hover:text-loss"
          >
            Clear
          </button>
        </div>
      ) : (
        // The list is a popover anchored to the field and portalled to the
        // body, as the search bar's is: drawn in place it sat at 94% over
        // the next field, whose label and placeholder read through it, and
        // any container that hid its overflow would have cut it off.
        <Popover
          open={showList}
          onOpenChange={(next) => {
            if (!next) setOpen(false)
          }}
        >
          <PopoverAnchor asChild>
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setOpen(true)
              }}
              onFocus={() => setOpen(true)}
              onBlur={() => setTimeout(() => setOpen(false), 120)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && matches[0]) choose(matches[0].id)
                if (e.key === 'Escape') setOpen(false)
              }}
              placeholder={placeholder ?? 'Search a champion'}
              className="control h-10 w-full px-3 text-sm placeholder:text-ink-faint"
            />
          </PopoverAnchor>
          <PopoverContent
            align="start"
            sideOffset={4}
            // Options for the field, which keeps focus: not a dialog.
            role="presentation"
            onOpenAutoFocus={(e) => e.preventDefault()}
            onCloseAutoFocus={(e) => e.preventDefault()}
            onInteractOutside={(e) => {
              if (e.target === inputRef.current) e.preventDefault()
            }}
            className="max-h-[min(16rem,var(--radix-popover-content-available-height))] w-(--radix-popover-trigger-width) overflow-y-auto rounded-lg border-line bg-panel p-0 py-1 text-ink shadow-[0_18px_44px_-12px_rgb(0_0_0/0.85)]"
          >
            <ul>
              {matches.map((c) => (
                <li key={c.id}>
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(c.id)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm text-ink-dim hover:bg-raised hover:text-ink"
                  >
                    {c.icon_url && (
                      <img src={c.icon_url} alt="" className="size-6 rounded-sm" loading="lazy" decoding="async" />
                    )}
                    {c.name}
                  </button>
                </li>
              ))}
            </ul>
          </PopoverContent>
        </Popover>
      )}
    </div>
  )
}
