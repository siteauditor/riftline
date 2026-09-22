import { useSyncExternalStore } from 'react'

import { renderNow } from '../lib/clock'
import { timeAgo } from '../lib/format'

// Relative times move by the minute, so the page follows them at that pace.
const TICK_MS = 60_000

function subscribe(onChange: () => void) {
  const id = window.setInterval(onChange, TICK_MS)
  return () => window.clearInterval(id)
}

/**
 * "3h ago", kept honest across a prerender.
 *
 * The server snapshot reads the clock the page was rendered with, so the
 * first client render matches the HTML byte for byte; the client snapshot
 * reads the real clock, and React moves to it once hydration is done, then
 * every minute after.
 */
export default function TimeAgo({ at, className }: { at: number; className?: string }) {
  const text = useSyncExternalStore(
    subscribe,
    () => timeAgo(at, Date.now()),
    () => timeAgo(at, renderNow()),
  )
  return <span className={className}>{text}</span>
}
