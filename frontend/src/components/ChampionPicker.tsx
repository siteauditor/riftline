import { useRef, useState, type KeyboardEvent } from 'react'
import { useQuery } from '@tanstack/react-query'

import { AnchoredList } from '@/components/ui/anchored-list'

import type { ChampionStatic } from '../lib/api'
import { searchChampions } from '../lib/championSearch'
import { queries } from '../lib/queries'
import { useCombobox } from '../lib/useCombobox'

interface Props {
  label: string
  placeholder: string
  onPick: (id: number) => void
  /** Champions already somewhere on the board, with where. Shown, not offered. */
  unavailable: ReadonlyMap<number, string>
  /** After the label, e.g. "2/4". */
  count?: string
  /** No room left on this side: the field is disabled and says so. */
  full?: boolean
  /** The field's id, so the board can put focus back on it. */
  inputId: string
}

/**
 * Add a champion by typing, in champion select, fast.
 *
 * A real combobox: the arrows move through the matches, Enter takes the
 * highlighted one or, with nothing highlighted, the best match for what is
 * typed (never the first champion of an empty list, which added Aatrox), and
 * Escape closes. A champion already on the board stays in the list, greyed,
 * with where it is, so the list does not seem to have lost them. The list opens
 * on typing, a click or the down arrow, not on focus: tabbing through the board
 * dropped a list over the next field every time.
 */
export default function ChampionPicker({ label, placeholder, onPick, unavailable, count, full, inputId }: Props) {
  const [query, setQuery] = useState('')
  const fieldRef = useRef<HTMLInputElement>(null)
  const { data } = useQuery({ ...queries.champions(), staleTime: 6 * 60 * 60 * 1000 })

  const options = searchChampions(data?.champions ?? [], query).map((champion) => ({
    key: String(champion.id),
    champion,
    disabled: unavailable.has(champion.id),
  }))
  const combo = useCombobox()
  const list = combo.bind(options, (option) => pick(option.champion))
  const typed = query.trim() !== ''
  const shown = combo.open && !full && (options.length > 0 || typed)

  function pick(champion: ChampionStatic) {
    onPick(champion.id)
    setQuery('')
    combo.close()
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (list.onKeyDown(event)) return
    if (event.key !== 'Enter' || event.nativeEvent.isComposing) return
    event.preventDefault()
    const target =
      list.active && !list.active.disabled
        ? list.active
        : typed
          ? options.find((o) => !o.disabled)
          : undefined
    if (target) pick(target.champion)
  }

  return (
    <div>
      <label htmlFor={inputId} className="mb-1 flex items-baseline justify-between text-xs text-ink-faint">
        <span>{label}</span>
        {count && <span className="tnum">{count}</span>}
      </label>
      <AnchoredList
        open={shown}
        onDismiss={combo.close}
        anchorRef={fieldRef}
        className="max-h-[min(16rem,var(--radix-popover-content-available-height))] overflow-y-auto"
        anchor={
          <input
            ref={fieldRef}
            id={inputId}
            value={query}
            disabled={full}
            {...list.inputProps(shown)}
            onChange={(e) => {
              setQuery(e.target.value)
              combo.setOpen(true)
              combo.setActiveKey(null)
            }}
            onMouseDown={() => combo.setOpen(true)}
            onBlur={combo.close}
            onKeyDown={onKeyDown}
            placeholder={full ? 'Full' : placeholder}
            spellCheck={false}
            autoComplete="off"
            className="control h-10 w-full px-3 text-sm placeholder:text-ink-faint disabled:cursor-not-allowed disabled:opacity-60"
          />
        }
      >
        <ul id={combo.listId} role="listbox" aria-label={label} className="py-1">
          {options.map((option, i) => {
            const where = unavailable.get(option.champion.id)
            return (
              <li
                key={option.key}
                {...list.optionProps(option, i)}
                className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 text-sm ${
                  option.disabled
                    ? 'cursor-default text-ink-faint'
                    : option.key === combo.activeKey
                      ? 'bg-raised text-ink'
                      : 'text-ink-dim'
                }`}
              >
                {option.champion.icon_url ? (
                  <img
                    src={option.champion.icon_url}
                    alt=""
                    className={`size-6 rounded-sm ${option.disabled ? 'opacity-40' : ''}`}
                    loading="lazy"
                    decoding="async"
                  />
                ) : (
                  <span aria-hidden className="size-6 rounded-sm bg-raised" />
                )}
                <span className="min-w-0 flex-1 truncate">{option.champion.name}</span>
                {where && <span className="shrink-0 text-[11px]">{where}</span>}
              </li>
            )
          })}
        </ul>
        {typed && options.length === 0 && (
          <p className="px-3 py-2 text-xs text-ink-faint">No champion matches “{query.trim()}”.</p>
        )}
      </AnchoredList>
    </div>
  )
}
