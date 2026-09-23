import * as React from 'react'
import { Tabs as TabsPrimitive } from 'radix-ui'

import { cn } from '@/lib/utils'

/**
 * Tabs, on Radix, in the site's one tab style: a row on a hairline with the
 * active tab underlined in gold. Radix gives them the tab roles, arrow-key
 * movement between tabs and one tab stop for the whole row.
 *
 * The underline slides. Each trigger draws its own gold edge, which is what
 * a prerendered page shows before any script runs; once mounted, the list
 * measures the active trigger and lays a bar over that edge which moves
 * between tabs, so a change reads as the line travelling rather than
 * reappearing somewhere else.
 */

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn('flex flex-col', className)} {...props} />
}

function TabsList({ className, children, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  const ref = React.useRef<HTMLDivElement>(null)
  const [bar, setBar] = React.useState<{ left: number; width: number } | null>(null)

  React.useEffect(() => {
    const list = ref.current
    if (!list) return
    const measure = () => {
      const active = list.querySelector<HTMLElement>('[data-slot=tabs-trigger][data-state=active]')
      if (!active) {
        setBar(null)
        return
      }
      const a = active.getBoundingClientRect()
      const l = list.getBoundingClientRect()
      setBar({ left: a.left - l.left, width: a.width })
    }
    measure()
    const changes = new MutationObserver(measure)
    changes.observe(list, { subtree: true, attributes: true, attributeFilter: ['data-state'] })
    const sizes = new ResizeObserver(measure)
    sizes.observe(list)
    return () => {
      changes.disconnect()
      sizes.disconnect()
    }
  }, [])

  return (
    <TabsPrimitive.List
      ref={ref}
      data-slot="tabs-list"
      className={cn('relative flex flex-wrap items-end gap-x-1 border-b border-line-soft', className)}
      {...props}
    >
      {children}
      {bar && (
        <span
          aria-hidden
          className="pointer-events-none absolute -bottom-px h-0.5 rounded-full bg-gold shadow-[0_0_12px_0_var(--color-gold)] transition-[left,width] duration-300 ease-out"
          style={{ left: bar.left, width: bar.width }}
        />
      )}
    </TabsPrimitive.List>
  )
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        '-mb-px border-b-2 border-transparent px-3 py-2 font-display text-sm font-600 whitespace-nowrap text-ink-dim transition-colors outline-none',
        'hover:text-ink focus-visible:text-ink data-[state=active]:border-gold data-[state=active]:text-gold-bright',
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
