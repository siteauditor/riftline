import type { PairEntry } from './api'

/** How many of these records are strong enough to call either way. */
export function calledCount(rows: PairEntry[]): number {
  return rows.filter((r) => r.call !== 'level').length
}

/** The patches a list of records was read over, newest first, in words. */
export function pairPatches(rows: PairEntry[]): string {
  const patches = [...new Set(rows.flatMap((r) => r.patches))].sort((a, b) =>
    b.localeCompare(a, 'en-US', { numeric: true }),
  )
  return patches.join(' and ')
}
