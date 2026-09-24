import type { MetaResponse } from './api'

/**
 * The tier list's words about its own letters, apart from the page so they
 * can be tested: the page module may export only its component.
 */

/**
 * What a letter is, said once for the whole list rather than on every badge.
 * On 16.18 the games separated 8 of 247 picks as better than even and 8 as
 * worse, while the letters give 28 an S: a letter is a place in the ranking,
 * and the list says so.
 */
export function tierLegend(floor: number): string {
  return (
    `A place within the role on this patch, among champions with ${floor} or more games there: ` +
    'S is the top tenth, then A, B, C and D. The ranking is by the low end of each win rate ' +
    'range, so a letter is a place in that order, not a measured gap, and a few games can move it.'
  )
}

/** How many of the listed picks the games tell apart from an even win rate. */
export function separationLine(
  data: Pick<MetaResponse, 'patch' | 'separated_above' | 'separated_below'>,
  shown: number,
): string {
  const { separated_above: above, separated_below: below } = data
  const lead =
    above + below === 0
      ? `On patch ${data.patch} the games do not yet show any of these ${shown} picks to be better or worse than even.`
      : `On patch ${data.patch} the games show ${above} of these ${shown} picks to be better than even and ${below} to be worse: their whole range sits above or below 50%.`
  return `${lead} The letters rank the rest by the low end of their range, so a few games can move them.`
}

/** Why a row carries no letter, for a screen reader: the badge shows a dash. */
export function missingTierReason(games: number, floor: number): string {
  return games < floor ? `No letter: under ${floor} games` : 'No letter: too few champions in this role to rank'
}
