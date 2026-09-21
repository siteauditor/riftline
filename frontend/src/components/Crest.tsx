import { tierColor, tierLabel } from '../lib/format'
import { crestUrl } from '../lib/rankArt'

/**
 * A rank as its crest.
 *
 * Riot ships these, every competitor shows them, and players read the shape
 * before they read the word. The site used to draw ranks as coloured text
 * only, on the reasoning that the colour identifies the tier at any size; it
 * does, but it also made a Challenger look exactly like a Bronze with a
 * different hue, which is not how anyone experiences rank.
 *
 * Community Dragon's mini crests are 1.5 to 2.5 KB of SVG each, so they cost
 * about as much as the text they replace. The colour still does the work in
 * dense rows: this is the crest plus the tier's own colour, not art instead of
 * information.
 */
const SIZES = { sm: 'size-5', md: 'size-7', lg: 'size-10' } as const

export default function Crest({
  tier,
  division,
  size = 'md',
  className,
}: {
  tier?: string | null
  division?: string | null
  size?: keyof typeof SIZES
  className?: string
}) {
  if (!tier) return null
  return (
    <img
      src={crestUrl(tier)}
      alt=""
      aria-hidden
      loading="lazy"
      title={tierLabel(tier, division)}
      className={`${SIZES[size]} shrink-0 ${className ?? ''}`}
      style={{ filter: `drop-shadow(0 0 6px color-mix(in srgb, ${tierColor(tier)} 45%, transparent))` }}
    />
  )
}
