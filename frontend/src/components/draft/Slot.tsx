import { useId } from 'react'

import ChampionPicker from '../ChampionPicker'
import Hint from '../Hint'
import type { ChampionStatic } from '../../lib/api'

/**
 * One side of the board: a picker and the champions already on it.
 *
 * The chips' buttons say what they do ("Remove Ahri"), because a button named
 * only "Ahri" told a screen reader nothing about pressing it. After a removal
 * focus goes to the next chip, else the one before, else back to the field:
 * it used to fall to the page body, and a keyboard user had to find the board
 * again.
 */
export default function Slot({
  label,
  placeholder,
  ids,
  cap,
  championById,
  unavailable,
  onAdd,
  onRemove,
  lane,
  onToggleLane,
  roleNote,
}: {
  label: string
  placeholder: string
  ids: number[]
  /** How many this side holds in a draft. */
  cap: number
  championById: Map<number, ChampionStatic>
  unavailable: ReadonlyMap<number, string>
  onAdd: (id: number) => void
  onRemove: (id: number) => void
  /** The enemy side only: who is in your lane, and how to change it. */
  lane?: number | null
  onToggleLane?: (id: number) => void
  /** A word about each champion's likely role, as "Mid 86%". */
  roleNote?: (id: number) => string | null
}) {
  const id = useId()
  const inputId = `${id}-input`
  const chipId = (champion: number) => `${id}-chip-${champion}`
  const name = (champion: number) => championById.get(champion)?.name ?? `Champion ${champion}`

  function remove(champion: number, index: number) {
    const next = ids[index + 1] ?? ids[index - 1]
    onRemove(champion)
    requestAnimationFrame(() => {
      const target = next === undefined ? document.getElementById(inputId) : document.getElementById(chipId(next))
      target?.focus()
    })
  }

  return (
    <div>
      <ChampionPicker
        label={label}
        placeholder={placeholder}
        inputId={inputId}
        onPick={onAdd}
        unavailable={unavailable}
        full={ids.length >= cap}
        count={ids.length > 0 ? `${ids.length}/${cap}` : undefined}
      />
      {ids.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {ids.map((champion, index) => {
            const icon = championById.get(champion)?.icon_url
            const marked = lane === champion
            return (
              <li
                key={champion}
                className={`flex items-center rounded-sm border bg-raised text-xs ${
                  marked ? 'border-gold text-gold-bright' : 'border-line text-ink-dim'
                }`}
              >
                <button
                  id={chipId(champion)}
                  type="button"
                  onClick={() => remove(champion, index)}
                  aria-label={`Remove ${name(champion)}`}
                  className="flex items-center gap-1.5 rounded-sm py-1 pl-1 pr-1.5 transition-colors outline-none hover:text-loss focus-visible:ring-2 focus-visible:ring-accent/60 pointer-coarse:py-2"
                >
                  {icon && <img src={icon} alt="" className="size-4 rounded-sm" />}
                  {name(champion)}
                  <span aria-hidden>✕</span>
                </button>
                {roleNote?.(champion) && (
                  <span className="tnum border-l border-line px-1.5 py-1 text-[10px] text-ink-faint">
                    {roleNote(champion)}
                  </span>
                )}
                {onToggleLane && (
                  <Hint
                    text={
                      marked
                        ? 'Counted as your lane opponent'
                        : `Mark ${name(champion)} as your lane opponent`
                    }
                  >
                    <button
                      type="button"
                      onClick={() => onToggleLane(champion)}
                      aria-pressed={marked}
                      aria-label={`${name(champion)} is my lane opponent`}
                      className={`border-l px-1.5 py-1 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent/60 pointer-coarse:py-2 ${
                        marked
                          ? 'border-gold/40 text-gold-bright'
                          : 'border-line text-ink-faint hover:text-ink'
                      }`}
                    >
                      {marked ? 'in my lane' : 'lane'}
                    </button>
                  </Hint>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
