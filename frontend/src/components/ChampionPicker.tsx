import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

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

  return (
    <div className="relative">
      <span className="mb-1 block text-xs text-ink-faint">{label}</span>

      {selected ? (
        <div className="flex h-10 items-center gap-2 frame px-2">
          {selected.icon_url && (
            <img src={selected.icon_url} alt="" className="size-7 rounded-sm" />
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
        <input
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
      )}

      {open && !selected && matches.length > 0 && (
        <ul className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto frame py-1 shadow-xl">
          {matches.map((c) => (
            <li key={c.id}>
              <button
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(c.id)}
                className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm text-ink-dim hover:bg-raised hover:text-ink"
              >
                {c.icon_url && (
                  <img src={c.icon_url} alt="" className="size-6 rounded-sm" />
                )}
                {c.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
