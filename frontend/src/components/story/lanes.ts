import type { LaneLabel } from '../../lib/api'

/** What each lane label says where a person reads it. */
export const LANE_TEXT: Record<LaneLabel, string> = {
  won_big: 'Won big',
  won: 'Won lane',
  even: 'Even lane',
  lost: 'Lost lane',
  lost_big: 'Lost big',
}

export function laneColor(label: LaneLabel): string {
  if (label === 'won' || label === 'won_big') return 'var(--color-win)'
  if (label === 'lost' || label === 'lost_big') return 'var(--color-loss)'
  return 'var(--color-ink-dim)'
}

/** A game clock from milliseconds: 1,530,000 reads "25:30". */
export function clock(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

/** Win chance, 0 to 1, as signed points: 0.123 reads "+12.3". */
export function points(delta: number): string {
  const value = delta * 100
  return `${value >= 0 ? '+' : '-'}${Math.abs(value).toFixed(1)}`
}
