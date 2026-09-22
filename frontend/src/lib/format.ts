/** Formatting helpers shared across views. */

/** Rank tier -> the colour players already associate with it. */
export const TIER_COLORS: Record<string, string> = {
  IRON: 'var(--color-iron)',
  BRONZE: 'var(--color-bronze)',
  SILVER: 'var(--color-silver)',
  GOLD: 'var(--color-gold-tier)',
  PLATINUM: 'var(--color-platinum)',
  EMERALD: 'var(--color-emerald)',
  DIAMOND: 'var(--color-diamond)',
  MASTER: 'var(--color-master)',
  GRANDMASTER: 'var(--color-grandmaster)',
  CHALLENGER: 'var(--color-challenger)',
}

/**
 * Colour for a win rate.
 *
 * Gold for genuinely strong, blue for winning, dim for not. `strong` moves
 * because the bar differs by subject: 55% on a champion's item build is
 * remarkable, while a player's own pool is read against 60%.
 */
export function winRateColor(rate: number, strong = 0.55): string {
  if (rate >= strong) return 'var(--color-gold-bright)'
  if (rate >= 0.5) return 'var(--color-win)'
  return 'var(--color-ink-dim)'
}

/**
 * Colour for a Riftline score.
 *
 * The same three-step ramp as `kdaColor`, on the scale the score actually uses:
 * 5.0 is the corpus median by construction, so the neutral band sits there
 * rather than at an arbitrary threshold.
 */
export function scoreColor(score: number): string {
  if (score >= 7.5) return 'var(--color-gold-bright)'
  if (score >= 5) return 'var(--color-win)'
  if (score >= 3) return 'var(--color-ink-dim)'
  return 'var(--color-loss)'
}

export function tierColor(tier?: string | null): string {
  if (!tier) return 'var(--color-ink-faint)'
  return TIER_COLORS[tier.toUpperCase()] ?? 'var(--color-ink-faint)'
}

export function tierLabel(tier?: string | null, division?: string | null): string {
  if (!tier) return 'Unranked'
  const name = tier.charAt(0) + tier.slice(1).toLowerCase()
  // Master and above have no divisions.
  const apex = ['MASTER', 'GRANDMASTER', 'CHALLENGER'].includes(tier.toUpperCase())
  return apex || !division ? name : `${name} ${division}`
}

export function pct(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function compact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`
  return String(value)
}

/** "Sep 20". One locale and one zone, so a prerendered page and the browser
 *  that hydrates it spell the same day the same way. */
export function shortDate(epochMs: number): string {
  return new Date(epochMs).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export function duration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

/** "3 hours ago" style, tuned short enough for a dense list. `now` is a
 *  parameter so a prerendered page can say what was true when it was made. */
export function timeAgo(epochMs: number, now: number = Date.now()): string {
  const seconds = Math.max(0, (now - epochMs) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  const days = Math.floor(seconds / 86400)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  return months < 12 ? `${months}mo ago` : `${Math.floor(months / 12)}y ago`
}

export function kdaRatio(kills: number, deaths: number, assists: number): string {
  if (deaths === 0) return 'Perfect'
  return ((kills + assists) / deaths).toFixed(2)
}

/** Colour a KDA by how good it is, using the same scale players use casually. */
export function kdaColor(kda: number, deaths: number): string {
  if (deaths === 0 || kda >= 5) return 'var(--color-gold-bright)'
  if (kda >= 3) return 'var(--color-win)'
  if (kda >= 1.5) return 'var(--color-ink)'
  return 'var(--color-ink-dim)'
}

const POSITION_LABELS: Record<string, string> = {
  TOP: 'Top',
  JUNGLE: 'Jungle',
  MIDDLE: 'Mid',
  BOTTOM: 'Bot',
  UTILITY: 'Support',
}

/** 1st, 2nd, 3rd, 4th. A placement reads as an ordinal or not at all. */
export function ordinal(n: number): string {
  const teens = n % 100
  if (teens >= 11 && teens <= 13) return `${n}th`
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] ?? 'th'}`
}

export function positionLabel(position?: string | null): string {
  if (!position) return ''
  return POSITION_LABELS[position.toUpperCase()] ?? position
}

/** Parse "Name#TAG" into its parts, tolerating missing or spaced tags. */
export function parseRiotId(input: string): { name: string; tag: string } | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  const hash = trimmed.lastIndexOf('#')
  if (hash === -1) return null
  const name = trimmed.slice(0, hash).trim()
  const tag = trimmed.slice(hash + 1).trim()
  if (!name || !tag) return null
  return { name, tag }
}
