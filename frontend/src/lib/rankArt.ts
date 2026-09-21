/**
 * Riot's own rank crests, served by Community Dragon.
 *
 * Kept out of the component file so the URL shape can be imported anywhere
 * without dragging a component along, and so one change covers every page.
 */
const CREST_BASE =
  'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests'

const EMBLEM_BASE =
  'https://raw.communitydragon.org/latest/plugins/rcp-fe-lol-static-assets/global/default/images/ranked-emblem'

/** The small crest, 1.5 to 2.5 KB of SVG: for rows, badges and headers. */
export function crestUrl(tier: string): string {
  return `${CREST_BASE}/${tier.toLowerCase()}.svg`
}

/** The full emblem, for the one place a rank is the subject: the rank card. */
export function emblemUrl(tier: string): string {
  return `${EMBLEM_BASE}/emblem-${tier.toLowerCase()}.png`
}
