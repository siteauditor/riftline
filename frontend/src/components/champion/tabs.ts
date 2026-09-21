/**
 * The champion page's tabs, in two groups.
 *
 * Nine tabs in one row is a scroll bar at phone width, and the two halves
 * answer different questions: who the champion is, which no sample size
 * changes, and how it is doing, which is a slice of our games. The group label
 * says which half the reader is in.
 */
export const TAB_GROUPS = [
  { label: 'The champion', tabs: ['story', 'abilities', 'skins'] },
  { label: 'The numbers', tabs: ['build', 'runes', 'laning', 'counters', 'synergies', 'players'] },
] as const

export type ChampionTab = (typeof TAB_GROUPS)[number]['tabs'][number]

export const TAB_LABEL: Record<ChampionTab, string> = {
  story: 'Story',
  abilities: 'Abilities',
  skins: 'Skins',
  build: 'Build',
  runes: 'Runes',
  laning: 'Laning',
  counters: 'Counters',
  synergies: 'Synergies',
  players: 'Players',
}

const ALL_TABS = new Set<string>(TAB_GROUPS.flatMap((g) => g.tabs))

export function parseTab(value: string | null): ChampionTab | null {
  return value && ALL_TABS.has(value) ? (value as ChampionTab) : null
}

/** Slot numbers as skill orders write them: 1 to 4 are Q, W, E, R. */
export const SLOT_KEY = ['Q', 'W', 'E', 'R'] as const
