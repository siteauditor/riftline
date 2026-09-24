/**
 * When a player plays, in words.
 *
 * The profile draws the day as 24 bars, and each bar used to say its hour and
 * its count only in a hover title: nothing for a phone, a keyboard or a screen
 * reader, and 24 numbers to find the one fact the chart is for. This names it.
 */

/** "20:00" */
export const hourLabel = (hour: number) => `${String(((hour % 24) + 24) % 24).padStart(2, '0')}:00`

/**
 * The run of `width` hours with the most games, wrapping past midnight, and
 * its share of them; the earliest run wins a tie. Null with no games.
 */
export function busiestWindow(
  hours: readonly number[],
  width = 3,
): { start: number; end: number; games: number; share: number } | null {
  const total = hours.reduce((sum, games) => sum + games, 0)
  if (total === 0 || hours.length === 0) return null
  let best = -1
  let bestStart = 0
  for (let start = 0; start < hours.length; start += 1) {
    let games = 0
    for (let k = 0; k < width; k += 1) games += hours[(start + k) % hours.length] ?? 0
    if (games > best) {
      best = games
      bestStart = start
    }
  }
  return { start: bestStart, end: (bestStart + width) % hours.length, games: best, share: best / total }
}
