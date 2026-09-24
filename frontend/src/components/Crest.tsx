import type { CSSProperties } from 'react'

import { tierColor } from '../lib/format'
import { rankArtFit, rankArtSrc, type RankArtKind } from '../lib/rankArt'

/**
 * A rank as its crest, at a size that matches the type beside it.
 *
 * Riot ships these, every competitor shows them, and players read the shape
 * before they read the word. This is the only component in the app that draws
 * rank art, so the choice of asset belongs here rather than at the call sites:
 * the small steps take the vector mini crest, and the two steps where the rank
 * is the subject of the page take the full emblem.
 *
 * The frame is about twice the cap height of the largest type on its line,
 * which is how the steps below are set. The art inside it is cropped by
 * `lib/rankArt.ts`, because neither Riot asset fills the file it ships in.
 */
const STEPS = {
  /** 11px tracked label, inside a rank pill. */
  pill: { box: 'size-[18px]', kind: 'mini', glow: false },
  /** 16px tier type in a line of 14px text, in a profile's compact header. */
  inline: { box: 'size-6', kind: 'mini', glow: false },
  /** 16px/700 tier type under a 30 to 48px headline, on a profile. */
  line: { box: 'size-8', kind: 'mini', glow: false },
  /** 26px/700 tier type on the rank card. */
  card: { box: 'size-24', kind: 'emblem', glow: true },
  /** A 32 to 51px headline, on the ladder. */
  hero: { box: 'size-32', kind: 'emblem', glow: true },
} as const satisfies Record<string, { box: string; kind: RankArtKind; glow: boolean }>

export type CrestSize = keyof typeof STEPS

export default function Crest({
  tier,
  size,
  className,
}: {
  tier?: string | null
  size: CrestSize
  className?: string
}) {
  if (!tier) return null
  const step = STEPS[size]
  return (
    // The tier is always written out beside this, so the art is decoration: to
    // a screen reader, and to a pointer too. The hover title it carried said the
    // word printed next to it, and on the rank pill it hid the pill's own LP.
    <span
      aria-hidden
      className={`rank-art ${step.glow ? 'rank-art-glow' : ''} ${step.box} ${className ?? ''}`}
      style={{ '--accent': tierColor(tier), ...rankArtFit(tier, step.kind) } as CSSProperties}
    >
      <img
        src={rankArtSrc(tier, step.kind)}
        alt=""
        // Only the emblems are worth deferring. Ten lazy 18px crests in one
        // lobby row cost an intersection observation each and all paint at once.
        loading={step.kind === 'emblem' ? 'lazy' : undefined}
      />
    </span>
  )
}
