import type { CSSProperties } from 'react'

/**
 * Riot's own rank crests, served by Community Dragon, and where the art
 * actually sits inside each file.
 *
 * **The box is not the art.** Neither family fills the canvas it ships in, and
 * the amount they miss it by differs per tier, so sizing the box does not size
 * the crest. Measured on 2026-09-21 by reading the alpha channel of every
 * asset:
 *
 * - `ranked-emblem/emblem-*.png` is a 1280x720 frame (2560x1440 for platinum
 *   and emerald) holding an emblem that is 15% of its width for iron and 25%
 *   for challenger. The ladder header drew one in an 80x80 box at the CSS
 *   default `object-fit: fill`, so about 20x28 pixels of challenger were
 *   painted, squashed to 56% of their correct width.
 * - `ranked-mini-crests/*.svg` is ten different boxes: iron 17x12, bronze and
 *   silver 18x12, gold 17x13, platinum, emerald and diamond 20x20 (where the
 *   drawing occupies 65% of the height), master and above 17x15. Forcing all
 *   ten into one square box stretched seven of them, by 1.42x for iron.
 *
 * So each tier carries a crop instead: a zoom, and the offset from the canvas
 * centre to the art's own centre. `.rank-art` in `index.css` applies them. The
 * numbers are fractions of the frame and of the image's own box, so the same
 * three values are correct at 18px and at 128px.
 *
 * The URLs point at `latest/`, so Riot can recut these assets under us and this
 * table would go stale with no signal. The measuring script is
 * `measure-rank-art.mjs`: it reads the alpha bounding box of all twenty files
 * and prints this table, so it can be rebuilt in one run.
 */
const CREST_BASE =
  'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests'

const EMBLEM_BASE =
  'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblem'

/** The small crest, 1.5 to 2.5 KB of SVG: for pills and for a line of type. */
export function crestUrl(tier: string): string {
  return `${CREST_BASE}/${tier.toLowerCase()}.svg`
}

/** The full emblem, for the two places where the rank is the subject. */
export function emblemUrl(tier: string): string {
  return `${EMBLEM_BASE}/emblem-${tier.toLowerCase()}.png`
}

export type RankArtKind = 'mini' | 'emblem'

interface Fit {
  /** The image's width as a multiple of the frame's. */
  zoom: number
  /** Centring correction, as a percentage of the image's own box. */
  dx: string
  dy: string
}

/**
 * The crop per tier, computed from the measured alpha box as
 * `zoom = phi * Cw / max(inkW, inkH)` and `d = (0.5 - inkCentre / C) * 100%`.
 *
 * `phi` is how much of the frame the art fills: 0.92 for the mini crests, which
 * have nothing behind them, and 0.86 for the emblems, which leaves room for the
 * bloom to read as a halo rather than as a rectangle. Every tier's art ends up
 * the same width, and its height is whatever Riot drew: 65% of the frame for
 * iron, 86% for challenger. That difference is the tiers looking like
 * themselves, not an error.
 */
const TIER_ART: Record<string, Record<RankArtKind, Fit>> = {
  iron: { mini: { zoom: 0.976, dx: '-2.88%', dy: '2.84%' }, emblem: { zoom: 5.616, dx: '-0.08%', dy: '0.49%' } },
  bronze: { mini: { zoom: 1.034, dx: '0.00%', dy: '2.81%' }, emblem: { zoom: 4.664, dx: '-0.08%', dy: '0.90%' } },
  silver: { mini: { zoom: 1.034, dx: '0.00%', dy: '2.81%' }, emblem: { zoom: 4.234, dx: '0.00%', dy: '3.19%' } },
  gold: { mini: { zoom: 0.976, dx: '2.88%', dy: '0.00%' }, emblem: { zoom: 4.267, dx: '0.08%', dy: '2.15%' } },
  platinum: { mini: { zoom: 1.146, dx: '-0.12%', dy: '2.50%' }, emblem: { zoom: 4.194, dx: '-0.02%', dy: '3.47%' } },
  emerald: { mini: { zoom: 1.146, dx: '-0.12%', dy: '2.62%' }, emblem: { zoom: 3.783, dx: '-0.08%', dy: '3.02%' } },
  diamond: { mini: { zoom: 1.017, dx: '0.00%', dy: '2.62%' }, emblem: { zoom: 3.506, dx: '-0.08%', dy: '0.42%' } },
  master: { mini: { zoom: 0.976, dx: '-2.88%', dy: '0.00%' }, emblem: { zoom: 3.669, dx: '-0.08%', dy: '1.87%' } },
  grandmaster: { mini: { zoom: 0.976, dx: '-2.88%', dy: '0.00%' }, emblem: { zoom: 3.540, dx: '-0.04%', dy: '0.90%' } },
  challenger: { mini: { zoom: 0.976, dx: '-2.88%', dy: '0.00%' }, emblem: { zoom: 3.440, dx: '-0.08%', dy: '3.06%' } },
}

/** No crop, for a tier name we have never seen: the art then sits in its box the
 *  way it did before this table existed, minus the stretch. */
const NEUTRAL: Fit = { zoom: 1, dx: '0%', dy: '0%' }

export function rankArtFit(tier: string | null | undefined, kind: RankArtKind): CSSProperties {
  const fit = (tier ? TIER_ART[tier.toLowerCase()]?.[kind] : undefined) ?? NEUTRAL
  return {
    '--art-zoom': fit.zoom,
    '--art-dx': fit.dx,
    '--art-dy': fit.dy,
  } as CSSProperties
}

export function rankArtSrc(tier: string, kind: RankArtKind): string {
  return kind === 'emblem' ? emblemUrl(tier) : crestUrl(tier)
}
