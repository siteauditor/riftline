import { useEffect, useRef, useState, type CSSProperties } from 'react'

const DURATION_MS = 700

/**
 * Whether a figure mounting now should count. Only on a page the app
 * navigated to: on a prerendered page the figure is already at its value in
 * the HTML and the first client render must agree with it. App.tsx marks the
 * document as taken over after the first render, so while a page is being
 * hydrated the mark is absent, and on the server there is no document.
 * Reduced motion shows every value at once.
 */
function animates(): boolean {
  return (
    typeof document !== 'undefined' &&
    document.documentElement.dataset.hydrated === 'true' &&
    !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * A figure that counts up to its value when it appears.
 *
 * On a page the app navigated to it starts from zero; a change of value then
 * counts from the value shown to the new one, never from zero again, so a
 * live answer replacing a stored one moves rather than restarts.
 */
export default function CountUp({
  value,
  format = (n) => String(Math.round(n)),
  className,
  style,
}: {
  value: number
  format?: (n: number) => string
  className?: string
  style?: CSSProperties
}) {
  const [shown, setShown] = useState(() => (animates() ? 0 : value))
  const shownRef = useRef(shown)

  useEffect(() => {
    if (!animates()) return
    const from = shownRef.current
    const start = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION_MS)
      const eased = 1 - Math.pow(1 - t, 3)
      const next = from + (value - from) * eased
      shownRef.current = next
      setShown(next)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  // Read from the count only where the count runs. A page being hydrated
  // shows what its HTML shows, and reduced motion is never a frame behind.
  return (
    <span className={className} style={style}>
      {format(animates() ? shown : value)}
    </span>
  )
}
