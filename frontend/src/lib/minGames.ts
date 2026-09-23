/**
 * The sample floors a reader may choose, shared by every page that offers one.
 *
 * A select rather than a number box: the box could not be emptied, so
 * deleting "20" and typing "30" gave 130, and "2.5" went to the API and came
 * back as "Something went wrong".
 */
export const MIN_GAMES_PRESETS: readonly number[] = [5, 10, 20, 30, 50, 100]

/** The presets, plus the link's own floor when it is another number. */
export function minGamesOptions(current: number): { value: string; label: string }[] {
  const values = MIN_GAMES_PRESETS.includes(current)
    ? MIN_GAMES_PRESETS
    : [...MIN_GAMES_PRESETS, current].sort((a, b) => a - b)
  return values.map((v) => ({ value: String(v), label: `${v} games` }))
}

/**
 * The floor to offer when nothing clears the chosen one: the highest preset
 * that still shows something, else the most games any row has. Null when no
 * lower floor would show anything.
 */
export function lowerFloor(mostGames: number, current: number): number | null {
  const preset = [...MIN_GAMES_PRESETS].reverse().find((v) => v <= mostGames && v < current)
  if (preset !== undefined) return preset
  return mostGames > 0 && mostGames < current ? mostGames : null
}
