import { useEffect, useState } from 'react'

/**
 * When this page will ask Riot again, and a way to ask now.
 *
 * Counted against `dataUpdatedAt`, which the query client stamps on this
 * machine when the answer arrives. Deliberately not against the server's own
 * `checked_at`: differencing two machines' wall clocks measures the skew
 * between them, which is routinely tens of seconds, and the game clock on this
 * page already carries that scar.
 */
export default function PollClock({
  updatedAt,
  intervalMs,
  fetching,
  onCheck,
}: {
  updatedAt: number
  intervalMs: number
  fetching: boolean
  onCheck: () => void
}) {
  const [now, setNow] = useState(() => Date.now())
  // Held for ten seconds after a check. The server caches a spectator lookup
  // briefly, so an immediate second ask returns the same bytes and only looks
  // like it did something. The profile's update button learned this first.
  const [heldUntil, setHeldUntil] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const left = Math.max(0, intervalMs - (now - updatedAt))
  const seconds = Math.ceil(left / 1000)
  const held = fetching || now < heldUntil

  return (
    <span className="flex items-center gap-2 text-xs text-ink-faint">
      <span className="tnum">
        {fetching
          ? 'Checking now'
          : `Next check in ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`}
      </span>
      <button
        type="button"
        disabled={held}
        onClick={() => {
          setHeldUntil(Date.now() + 10_000)
          onCheck()
        }}
        className="control px-2 py-1 text-xs font-600 text-ink-dim transition-colors hover:text-ink disabled:opacity-40"
      >
        Check now
      </button>
    </span>
  )
}
