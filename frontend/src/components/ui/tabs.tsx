import * as React from 'react'
import { Tabs as TabsPrimitive } from 'radix-ui'

import { cn } from '@/lib/utils'
import { OWN_EDGE_CLASS, SLIDING_BAR_CLASS, useSlidingBar } from '@/lib/useSlidingBar'

/**
 * Tabs, on Radix, in the site's one tab style: a row on a hairline with the
 * active tab underlined in gold. Radix gives them the tab roles, arrow-key
 * movement between tabs and one tab stop for the whole row.
 *
 * The underline slides. Each trigger draws its own gold edge, which is what
 * a prerendered page shows before any script runs; once mounted, the list
 * lays a bar over that edge which moves between tabs, so a change reads as
 * the line travelling rather than reappearing somewhere else.
 */

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col', className)} {...props} />
}

function TabsList({ className, children, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  const { ref, bar } = useSlidingBar<HTMLDivElement>('[data-slot=tabs-trigger][data-state=active]', 'data-state')
  return (
    <TabsPrimitive.List
      ref={ref}
      data-slot="tabs-list"
      data-bar={bar ? '' : undefined}
      className={cn('relative flex flex-wrap items-end gap-x-1 border-b border-line-soft', className)}
      {...props}
    >
      {children}
      {bar && (
        <span aria-hidden className={SLIDING_BAR_CLASS} style={{ left: bar.left, top: bar.top, width: bar.width }} />
      )}
    </TabsPrimitive.List>
  )
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        '-mb-px rounded-sm border-b-2 border-transparent px-3 py-2 font-display text-sm font-600 whitespace-nowrap text-ink-dim transition-colors outline-none',
        'hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/60 data-[state=active]:text-gold-bright',
        OWN_EDGE_CLASS,
        'disabled:pointer-events-none disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content data-slot="tabs-content" className={cn('outline-none', className)} {...props} />
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
