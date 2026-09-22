import { useContext, useEffect } from 'react'

import { applyHead, HeadContext, type PageHead } from '../lib/head'

/**
 * Declare this page's head. Renders nothing.
 *
 * On the client it updates the document's marked tags after render, so a
 * prerendered head is edited in place and in-app navigation keeps the title
 * and the social card current. Under the prerenderer it hands the same values
 * to the collector, which writes them into the served HTML.
 *
 * A page renders it once, with data it already has: a champion page waits for
 * the champion before it knows its title, and shows the site default until
 * then.
 */
export default function Head(head: PageHead) {
  const collector = useContext(HeadContext)
  if (collector) collector.set(head)

  // Keyed on the serialised value, so a re-render with the same head is free.
  const serialised = JSON.stringify(head)
  useEffect(() => {
    if (collector) return
    applyHead(JSON.parse(serialised) as PageHead)
  }, [collector, serialised])

  return null
}
