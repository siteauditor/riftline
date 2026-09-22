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

declare global {
  interface Window {
    /** Epoch ms of the prerender, stamped into a prerendered page. */
    __RENDERED_AT__?: number
  }
}
