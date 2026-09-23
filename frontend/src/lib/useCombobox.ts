import { useId, useState, type KeyboardEvent, type MouseEvent } from 'react'

export interface ComboboxOption {
  /** Stable across renders: the highlight follows the key, not a position. */
  key: string
  disabled?: boolean
}

/**
 * A text field with a list of options under it: the ARIA combobox pattern.
 *
 * The field keeps focus the whole time and names the highlighted option with
 * `aria-activedescendant`; the arrows move the highlight (skipping disabled
 * options and wrapping at the ends), Escape closes the list, and the caller
 * decides what Enter does. The highlight is held by key rather than index,
 * because options arrive after keystrokes and an index would slide onto
 * whichever row landed there.
 *
 * The hook owns the open state and the highlight; `bind` joins them to this
 * render's options. The split is because a list can depend on being open: the
 * search bar only asks the server for suggestions while its list is open.
 * Extracted from the search bar, where it was written first, so the champion
 * picker could stop being a mouse-only list.
 */
export function useCombobox() {
  const listId = `${useId()}-list`
  const [open, setOpen] = useState(false)
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const optionId = (index: number) => `${listId}-${index}`

  function close() {
    setOpen(false)
    setActiveKey(null)
  }

  function bind<T extends ComboboxOption>(options: readonly T[], onPick: (option: T) => void) {
    const activeIndex = options.findIndex((o) => o.key === activeKey)

    function enabledFrom(start: number, step: 1 | -1): number {
      const n = options.length
      for (let i = 0; i < n; i++) {
        const index = (((start + step * i) % n) + n) % n
        if (!options[index].disabled) return index
      }
      return -1
    }

    function highlight(index: number) {
      if (index < 0) return
      setActiveKey(options[index].key)
      // A scrolling list keeps the highlighted row in view as the keys move it.
      requestAnimationFrame(() =>
        document.getElementById(optionId(index))?.scrollIntoView?.({ block: 'nearest' }),
      )
    }

    /** The keys the list owns. True when the key was handled here. */
    function onKeyDown(event: KeyboardEvent<HTMLInputElement>): boolean {
      // Enter and the arrows belong to the input method while a Korean or
      // Japanese name is still being composed.
      if (event.nativeEvent.isComposing) return false
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault()
        if (!open) {
          setOpen(true)
          return true
        }
        if (!options.length) return true
        highlight(
          event.key === 'ArrowDown'
            ? enabledFrom(activeIndex + 1, 1)
            : enabledFrom(activeIndex < 0 ? options.length - 1 : activeIndex - 1, -1),
        )
        return true
      }
      // Home and End move the caret unless an option is highlighted.
      if ((event.key === 'Home' || event.key === 'End') && open && activeIndex >= 0) {
        event.preventDefault()
        highlight(event.key === 'Home' ? enabledFrom(0, 1) : enabledFrom(options.length - 1, -1))
        return true
      }
      if (event.key === 'Escape' && open) {
        event.preventDefault()
        close()
        return true
      }
      return false
    }

    return {
      activeIndex,
      active: activeIndex >= 0 ? options[activeIndex] : null,
      onKeyDown,
      /** For the text field; `shown` is whether the list is actually on screen. */
      inputProps: (shown: boolean) => ({
        role: 'combobox' as const,
        'aria-autocomplete': 'list' as const,
        'aria-expanded': shown,
        'aria-controls': listId,
        'aria-activedescendant': shown && activeIndex >= 0 ? optionId(activeIndex) : undefined,
      }),
      optionProps: (option: T, index: number) => ({
        id: optionId(index),
        role: 'option' as const,
        'aria-selected': index === activeIndex,
        'aria-disabled': option.disabled || undefined,
        // Keeps focus in the field, so the blur that closes the list does not
        // land before the click that picks from it.
        onMouseDown: (event: MouseEvent) => event.preventDefault(),
        onMouseMove: () => {
          if (!option.disabled && option.key !== activeKey) setActiveKey(option.key)
        },
        onClick: () => {
          if (!option.disabled) onPick(option)
        },
      }),
    }
  }

  return { open, setOpen, close, activeKey, setActiveKey, listId, bind }
}
