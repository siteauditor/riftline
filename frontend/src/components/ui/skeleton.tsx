import { cn } from '@/lib/utils'

/**
 * A loading placeholder. No animation of its own: the breathing lives on the
 * container (`.skeleton-breathing`, index.css), so every placeholder in a
 * list changes together rather than rippling down the page.
 */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="skeleton" className={cn('rounded-[2px] bg-line-soft', className)} {...props} />
}

export { Skeleton }
