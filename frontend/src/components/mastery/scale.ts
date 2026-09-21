/**
 * The mastery level scale, in one place so the tiles and the legend cannot
 * drift apart.
 *
 * Riot's 2024 rework removed the level 7 cap, and levels now run without a
 * ceiling: measured on production on 2026-09-21, three real accounts topped out
 * at 232, 152 and 45. The old ramp stopped at "10+", which put 41 of one
 * player's 166 champions in a single colour, and it borrowed two tier tokens
 * and gold on the way. Tier colours are load bearing elsewhere on this site and
 * gold means earned, so mastery gets its own five steps.
 *
 * The bands below are not even, because the population is not: on the same
 * three accounts plus a fourth read across shards, levels 1 to 4 held 81, 107,
 * 88 and 95 champions while 50 and up held 7, 2, 0 and 0. The point of the top
 * band is that reaching it is rare.
 */
export interface LevelStep {
  /** Lowest level in this step. */
  from: number
  label: string
  color: string
  /** Ink for the level number drawn on this step, where one is drawn. */
  ink: string
}

export const UNPLAYED: LevelStep = {
  from: 0,
  label: 'Not played',
  color: 'var(--color-line)',
  ink: 'var(--color-ink-faint)',
}

/**
 * Five steps, highest first so a lookup can stop at the first match.
 *
 * The inks flip between step 2 and step 3 rather than running all the way down
 * one colour, because the level number sits on these swatches at 10px and the
 * contrast window has a hole in the middle: against the page's light ink a
 * swatch has to be dark, against near black it has to be light, and between
 * those two there is no text colour that clears 4.5:1. The old file found that
 * hole by hand and left two comments about it, at 2.12:1 and at "a step no text
 * colour could clear".
 */
export const LEVEL_STEPS: LevelStep[] = [
  { from: 50, label: '50 and up', color: 'var(--color-mastery-5)', ink: 'var(--color-deep)' },
  { from: 25, label: '25 to 49', color: 'var(--color-mastery-4)', ink: 'var(--color-deep)' },
  { from: 10, label: '10 to 24', color: 'var(--color-mastery-3)', ink: 'var(--color-deep)' },
  { from: 5, label: '5 to 9', color: 'var(--color-mastery-2)', ink: 'var(--color-ink)' },
  { from: 1, label: '1 to 4', color: 'var(--color-mastery-1)', ink: 'var(--color-ink)' },
]

export function levelStep(level: number): LevelStep {
  if (level <= 0) return UNPLAYED
  return LEVEL_STEPS.find((step) => level >= step.from) ?? LEVEL_STEPS[LEVEL_STEPS.length - 1]
}

/** The legend, lowest first, which is the order a scale is read in. */
export const LEGEND_STEPS: LevelStep[] = [...LEVEL_STEPS].reverse().concat(UNPLAYED)

/**
 * Three tile sizes, one per band.
 *
 * Fixed pixels rather than `1fr`: with a fractional track a seven champion core
 * would draw 129px tiles and an eleven champion core 96px ones, and the sizes
 * would stop meaning the same thing from one profile to the next.
 */
export const TILE_SIZE = { core: 96, middle: 56, tail: 32 } as const

export type TileSize = keyof typeof TILE_SIZE
