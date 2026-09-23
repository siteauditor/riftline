import { useEffect, useRef, useState } from 'react'

export interface Bar {
  left: number
  top: number
  width: number
}

/**
 * Where the active item of a row is, for an underline that slides to it.
 *
 * Measures the element matching `activeSelector` inside the container, and
 * measures again whenever `attribute` changes anywhere inside it or the
 * container resizes, so the bar follows a tab change, a route change and a
 * wrap onto a second line. Nothing on the server and nothing before mount:
 * a prerendered page shows each item's own static underline until then.
 */
export function useSlidingBar<T extends HTMLElement>(activeSelector: string, attribute: string) {
  const ref = useRef<T>(null)
  const [bar, setBar] = useState<Bar | null>(null)

  useEffect(() => {
    const list = ref.current
    if (!list) return
    const sizes = new ResizeObserver(() => measure())
    let watched: HTMLElement | null = null
    const measure = () => {
      const active = list.querySelector<HTMLElement>(activeSelector)
      if (active !== watched) {
        // The active item's own box: a font swap or a wrap moves it without
        // changing the list's width, which is all the list's box would show.
        if (watched) sizes.unobserve(watched)
        if (active) sizes.observe(active)
        watched = active
      }
      if (!active) {
        setBar(null)
        return
      }
      const a = active.getBoundingClientRect()
      const l = list.getBoundingClientRect()
      // Two pixels up from the item's bottom edge: where its own border sits,
      // so on a wrapped row the bar is under that row, not under the list.
      setBar({ left: a.left - l.left, top: a.bottom - l.top - 2, width: a.width })
    }
    measure()
    const changes = new MutationObserver(measure)
    changes.observe(list, { subtree: true, attributes: true, attributeFilter: [attribute] })
    sizes.observe(list)
    return () => {
      changes.disconnect()
      sizes.disconnect()
    }
  }, [activeSelector, attribute])

  return { ref, bar }
}

/** The bar itself, positioned by the caller inside a `relative` row. */
export const SLIDING_BAR_CLASS =
  'pointer-events-none absolute h-0.5 rounded-full bg-gold shadow-[0_0_12px_0_var(--color-gold)] transition-[left,top,width] duration-300 ease-out'

/**
 * On the items themselves: the item draws its own gold edge for a page
 * that has no bar yet (the prerendered HTML, or no script), and hands the
 * job to the bar once the row carries `data-bar`.
 */
export const OWN_EDGE_CLASS =
  'data-[state=active]:border-gold [[data-bar]_&]:data-[state=active]:border-transparent aria-[current=page]:border-gold [[data-bar]_&]:aria-[current=page]:border-transparent'
