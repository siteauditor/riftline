import { boardParams, parseBoard, type Board } from '../../lib/draftBoard'
import { useHydrated, useHydratedSearchParams } from '../../lib/searchParams'

/**
 * The draft board from the URL, and the one way to change it.
 *
 * Read through the hydration gate, because the prerendered HTML is the empty
 * board whatever the link says. Each change is one transform and one write,
 * applied to the URL as it is at the time of the change rather than as it was
 * when the page last rendered.
 */
export function useDraftBoard() {
  const [search, setSearch] = useHydratedSearchParams()
  const hydrated = useHydrated()
  const board = parseBoard(search)
  const update = (change: (board: Board) => Board) =>
    setSearch((current) => boardParams(change(parseBoard(current)), current), { replace: true })
  return { board, update, hydrated }
}
