/**
 * What a player's score components support saying about them.
 *
 * Each component is the average of their per-game percentiles in a role, and at
 * the depth a profile has (ten to a few dozen scored games) a gap of ten points
 * between two components is noise. The panel used to name the highest and the
 * lowest whatever they were, so "weakest at vision" was said of a 48 beside a
 * 55: on 2026-09-24, 17 of the 20 players with a breakdown got a weakness from
 * inside the middle band. A part is a strength from 65 and a weakness to 35, the
 * same bands the bars are coloured by, and a sentence claims only what falls
 * outside the middle.
 */

export const STRONG_FROM = 65
export const WEAK_TO = 35

export type Band = 'strong' | 'middle' | 'weak'

/** A percentile from 0 to 100, banded. */
export function band(value: number): Band {
  if (value >= STRONG_FROM) return 'strong'
  if (value <= WEAK_TO) return 'weak'
  return 'middle'
}

const list = (labels: string[]) =>
  labels.length <= 1 ? (labels[0] ?? '') : `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`

/**
 * The panel's sentence. Null when every part sits in the middle band: there is
 * then nothing the games support saying, and the page says so in other words.
 */
export function strengthsClaim(
  components: readonly { label: string; avg_percentile: number }[],
): string | null {
  const banded = components.map((c) => ({
    label: c.label.toLowerCase(),
    band: band(Math.round(c.avg_percentile * 100)),
  }))
  const strong = banded.filter((c) => c.band === 'strong').map((c) => c.label)
  const weak = banded.filter((c) => c.band === 'weak').map((c) => c.label)
  if (strong.length === 0 && weak.length === 0) return null

  const parts = [
    strong.length ? `Strong at ${list(strong)}` : null,
    weak.length ? `${strong.length ? 'weak' : 'Weak'} at ${list(weak)}` : null,
  ].filter(Boolean)
  const middle = banded.length - strong.length - weak.length
  return (
    `${parts.join(', ')}.` +
    (middle > 0 ? ' The rest sit in the middle band, where a gap is noise.' : '')
  )
}
