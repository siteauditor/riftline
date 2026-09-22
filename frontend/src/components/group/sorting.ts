import type { GroupMember } from '../../lib/api'

export type SortKey = 'rank' | 'games' | 'win_rate' | 'kda' | 'score' | 'cs' | 'damage'

export interface Column {
  key: Exclude<SortKey, 'rank'>
  label: string
  title: string
  value: (m: GroupMember) => number | null
  scoredOnly?: boolean
}

export const COLUMNS: Column[] = [
  { key: 'games', label: 'Games', title: 'Stored games in the queues chosen', value: (m) => m.games },
  { key: 'win_rate', label: 'Win rate', title: 'Share of those games won', value: (m) => m.win_rate },
  { key: 'kda', label: 'KDA', title: 'Kills and assists per death', value: (m) => m.kda },
  {
    key: 'score',
    label: 'Score',
    title: 'Average Riftline score, 0 to 10, over the scored games',
    value: (m) => m.avg_score,
    scoredOnly: true,
  },
  { key: 'cs', label: 'CS/m', title: 'Minions and monsters per minute', value: (m) => m.cs_per_min },
  {
    key: 'damage',
    label: 'Dmg/m',
    title: 'Damage to champions per minute',
    value: (m) => m.damage_per_min,
  },
]

export const SORT_KEYS: SortKey[] = ['rank', ...COLUMNS.map((c) => c.key)]

/**
 * Official rank is the server's order. Every other column sorts highest first,
 * with withheld figures last rather than read as zero.
 */
export function sortMembers(members: GroupMember[], sort: SortKey): GroupMember[] {
  if (sort === 'rank') return members
  const column = COLUMNS.find((c) => c.key === sort)
  if (!column) return members
  return [...members].sort((a, b) => {
    const va = column.value(a)
    const vb = column.value(b)
    if (va === null && vb === null) return 0
    if (va === null) return 1
    if (vb === null) return -1
    return vb - va
  })
}
