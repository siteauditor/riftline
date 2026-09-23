import type { DamageShares } from './api'

/**
 * The three damage types and their colours, shared by the draft's team bar and
 * its row notes. The colours are the `--color-physical`, `--color-magic` and
 * `--color-true` tokens in `index.css`.
 */

export type DamageType = keyof DamageShares

export const DAMAGE_TYPES: { key: DamageType; bar: string; text: string }[] = [
  { key: 'physical', bar: 'bg-physical', text: 'text-physical' },
  { key: 'magic', bar: 'bg-magic', text: 'text-magic' },
  { key: 'true', bar: 'bg-true', text: 'text-true' },
]

export const DAMAGE_TEXT: Record<DamageType, string> = {
  physical: 'text-physical',
  magic: 'text-magic',
  true: 'text-true',
}

/** The type a pick has to deal mostly to pull a side leaning this way back. */
export function otherType(leaning: DamageType): string {
  if (leaning === 'physical') return 'magic'
  if (leaning === 'magic') return 'physical'
  return 'physical or magic'
}

/** A pick's main damage type, from its own shares. */
export function mainType(shares: DamageShares): DamageType {
  return DAMAGE_TYPES.map((t) => t.key).reduce((best, key) => (shares[key] > shares[best] ? key : best))
}
