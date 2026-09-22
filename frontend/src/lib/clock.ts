/**
 * When "now" was, for text that depends on it.
 *
 * A prerendered page says "3h ago" as of the moment it was rendered, and the
 * browser that hydrates it hours later must first render the same words, or
 * React reports a mismatch and re-renders the page from scratch. So the
 * prerenderer stamps its render time into the page, hydration reads the
 * clock from there, and only after hydration does the page move to the real
 * clock. On a page that was not prerendered there is no stamp and "now" is
 * simply now.
 */

import { useSyncExternalStore } from 'react'

let serverNow: number | null = null

/** Set by the server entry for the length of one render. */
export function setServerNow(ms: number | null): void {
  serverNow = ms
}

/** The clock the first render must use. */
export function renderNow(): number {
  if (serverNow !== null) return serverNow
  if (typeof window !== 'undefined' && typeof window.__RENDERED_AT__ === 'number') {
    return window.__RENDERED_AT__
  }
  return Date.now()
}

// One clock for every label that needs "now" as a number, ticking every
// five seconds: fast enough for a cooldown counter, cheap enough to leave
// running. The snapshot is a stored value, not `Date.now()` itself, because
// React reads a snapshot twice per render and treats two different answers
// as a store that never settles.
const TICK_MS = 5_000
const listeners = new Set<() => void>()
let clientNow = Date.now()
let timer: number | null = null

function subscribe(listener: () => void) {
  listeners.add(listener)
  if (timer === null) {
    clientNow = Date.now()
    timer = window.setInterval(() => {
      clientNow = Date.now()
      listeners.forEach((notify) => notify())
    }, TICK_MS)
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0 && timer !== null) {
      window.clearInterval(timer)
      timer = null
    }
  }
}

/**
 * "Now", safe to render: the render clock while hydrating, so the first
 * client render matches the prerendered HTML, and the real clock after.
 */
export function useNow(): number {
  return useSyncExternalStore(subscribe, () => clientNow, renderNow)
}

const never = () => () => {}

/**
 * The viewer's timezone, in whole hours from UTC. The server has no viewer,
 * so a prerendered page is laid out in UTC and moves to local time once the
 * browser has hydrated it; rendering the local offset straight away would
 * mismatch the HTML for everyone east or west of Greenwich.
 */
export function useLocalOffsetHours(): number {
  return useSyncExternalStore(
    never,
    () => Math.round(-new Date().getTimezoneOffset() / 60),
    () => 0,
  )
}

declare global {
  interface Window {
    /** Epoch ms of the prerender, stamped into a prerendered page. */
    __RENDERED_AT__?: number
  }
}
