import { useEffect, useState } from 'react'

/** What can be debounced: values compared by what they are, not by identity. */
export type Settleable = string | number | boolean | null | undefined

/**
 * A value that settles.
 *
 * Used where every keystroke would otherwise be a request: the search box's
 * suggestions and the draft board's re-ranking. 150 to 250 ms is under the gap
 * between keystrokes of a steady typist, so a whole word costs one request.
 *
 * Primitives only. The effect below runs when the value's identity changes, and
 * an object built during render is a new object every render: the draft board
 * passed one and re-rendered every 250 ms for as long as the page was open
 * (measured 2026-09-24, twelve timers in three idle seconds). Serialise first.
 */
export function useDebounced<T extends Settleable>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}
