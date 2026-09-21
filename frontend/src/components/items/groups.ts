import type { ItemSummary } from '../../lib/api'

/**
 * Filters by what an item gives, over Riot's own item tags.
 *
 * Tags rather than the stat lines, because the tags are one fixed vocabulary
 * while the stat labels are prose ("Base Mana Regen", "Heal and Shield Power").
 * Ability haste matches either tag: Riot still carries CooldownReduction on
 * items that give haste.
 */
export const STAT_FILTERS = [
  { key: 'ad', label: 'Attack damage', tags: ['Damage'] },
  { key: 'ap', label: 'Ability power', tags: ['SpellDamage'] },
  { key: 'as', label: 'Attack speed', tags: ['AttackSpeed'] },
  { key: 'crit', label: 'Crit', tags: ['CriticalStrike'] },
  { key: 'hp', label: 'Health', tags: ['Health'] },
  { key: 'armor', label: 'Armor', tags: ['Armor'] },
  { key: 'mr', label: 'Magic resist', tags: ['SpellBlock'] },
  { key: 'haste', label: 'Ability haste', tags: ['AbilityHaste', 'CooldownReduction'] },
  { key: 'mana', label: 'Mana', tags: ['Mana', 'ManaRegen'] },
  { key: 'speed', label: 'Move speed', tags: ['NonbootsMovement', 'Boots'] },
] as const

export type StatFilterKey = (typeof STAT_FILTERS)[number]['key']

export function matchesFilter(item: ItemSummary, key: StatFilterKey | null, query: string): boolean {
  if (query && !item.name.toLowerCase().includes(query)) return false
  if (!key) return true
  const filter = STAT_FILTERS.find((f) => f.key === key)
  return !filter || filter.tags.some((tag) => item.tags.includes(tag))
}

/** "1st item" to "4th or later", for the slot a finished item was bought in. */
export function slotLabel(slot: number): string {
  return ['1st item', '2nd item', '3rd item', '4th or later'][slot - 1] ?? `${slot}th item`
}

/** Points against the same slot, signed: 0.021 reads "+2.1". */
export function points(delta: number): string {
  const value = delta * 100
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}`
}
