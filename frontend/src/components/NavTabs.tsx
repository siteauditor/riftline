import { NavLink } from 'react-router-dom'

import { cn } from '@/lib/utils'
import { OWN_EDGE_CLASS, SLIDING_BAR_CLASS, useSlidingBar } from '@/lib/useSlidingBar'

export interface NavTab {
  to: string
  label: string
  end?: boolean
}

/**
 * Tabs that are pages: the Overview / Champions / Mastery / Live strip on a
 * player. Links, not buttons, so each has an address; the same gold
 * underline as the in-page tabs, and the same bar sliding between them on
 * a route change, measured from the link the router marks current.
 */
export default function NavTabs({
  tabs,
  label,
  className,
}: {
  tabs: NavTab[]
  label?: string
  className?: string
}) {
  const { ref, bar } = useSlidingBar<HTMLElement>('a[aria-current="page"]', 'aria-current')
  return (
    <nav
      ref={ref}
      aria-label={label}
      data-bar={bar ? '' : undefined}
      className={cn('relative flex flex-wrap gap-1 text-sm', className)}
    >
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          end={tab.end}
          to={tab.to}
          viewTransition
          className={({ isActive }) =>
            cn(
              'rounded-sm border-b-2 border-transparent px-3 pb-1.5 pt-1 font-display font-600 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent/60',
              OWN_EDGE_CLASS,
              isActive ? 'text-gold-bright' : 'text-ink-dim hover:text-ink',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
      {bar && (
        <span aria-hidden className={SLIDING_BAR_CLASS} style={{ left: bar.left, top: bar.top, width: bar.width }} />
      )}
    </nav>
  )
}
