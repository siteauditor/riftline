import type { Position } from '../../lib/api'

/**
 * Summoner's Rift sides and lanes, shared by the lane layout and the bans.
 *
 * Riot's own ids: blue is 100 and red is 200, and the other side of a lane is
 * `300 - team_id`. Only modes that have sides use these. Arena reports eight
 * teams of two, so `TeamView` groups by whatever ids it is given instead.
 */
export const BLUE = 100
export const RED = 200

export const LANES: Position[] = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
