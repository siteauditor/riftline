import { useEffect, useState } from 'react'

/**
 * A value that settles.
 *
 * Used where every keystroke would otherwise be a request: the search box's
 * suggestions and the draft board's re-ranking. 150 to 250 ms is under the gap
 * between keystrokes of a steady typist, so a whole word costs one request.
 */
export function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return settled
}
