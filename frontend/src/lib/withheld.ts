import type { MatchSummary } from './api'

export type ScoreWithheld = NonNullable<MatchSummary['score_withheld']>

/**
 * Why a game has no Riftline score, as a row shows it: a few words in the row,
 * the whole reason in its hint. The row used to show a dash whose contrast was
 * 1.3 to 1, and called every unscored game "not scored yet", including the
 * normal and Swiftplay games a queue too thin to measure withholds for good.
 * The reasons are the API's (`withheld_reason` in `backend/app/services/scores.py`),
 * in the order scoring checks them.
 */
export const WITHHELD: Record<ScoreWithheld, { short: string; long: string }> = {
  remake: {
    short: 'Remake, no score',
    long: 'This game was a remake, so there is nothing to score.',
  },
  not_ten: {
    short: 'No score in this mode',
    long: 'This mode is not five against five, so there is no lane role to place a player in.',
  },
  no_roles: {
    short: 'No roles to score',
    long: 'This mode has no lane roles, and every part of the score is measured against a role.',
  },
  thin_queue: {
    short: 'Too few games to score',
    long: 'Riftline holds too few games in this queue to measure a score against.',
  },
  not_scored_yet: {
    short: 'Not scored yet',
    long: 'This game has not been scored yet.',
  },
}

/** The words for a game with no score, or null when it has one. */
export function withheldText(reason: ScoreWithheld | null | undefined) {
  return reason ? WITHHELD[reason] : null
}
