import { cn } from '@/lib/utils'

/**
 * A loading placeholder with a light passing over it: the `.skeleton` class
 * in index.css carries the shimmer, so the rule and its keyframes live in
 * one place and the placeholders in StateViews share it.
 */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="skeleton" className={cn('skeleton', className)} {...props} />
}

export { Skeleton }
