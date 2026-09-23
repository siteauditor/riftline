import * as React from 'react'
import { Link } from 'react-router-dom'

import { cn } from '@/lib/utils'

/**
 * A row of choices where one, or several, is on: queue filters, roles, item
 * stats, skin lines. Pills, in the header nav's language: the chosen one
 * sits on a teal tint, the rest are quiet text that lights on hover. Every
 * filter on the site used to draw its own underlined buttons; this is the
 * one shape they share now.
 */

function ChipGroup({ label, className, ...props }: React.ComponentProps<'div'> & { label?: string }) {
  return (
    <div
      role="group"
      aria-label={label}
      data-slot="chip-group"
      className={cn('flex flex-wrap items-center gap-1.5', className)}
      {...props}
    />
  )
}

const chipClass = (active: boolean, size: 'default' | 'sm', className?: string) =>
  cn(
    'inline-flex cursor-pointer items-center gap-1.5 rounded-full font-display font-600 whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent/60 disabled:pointer-events-none disabled:opacity-50',
    size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-sm',
    active ? 'bg-accent/12 text-accent-bright' : 'text-ink-dim hover:bg-white/[0.05] hover:text-ink',
    className,
  )

function Chip({
  active,
  size = 'default',
  className,
  type = 'button',
  ...props
}: React.ComponentProps<'button'> & { active: boolean; size?: 'default' | 'sm' }) {
  return (
    <button
      type={type}
      aria-pressed={active}
      data-slot="chip"
      className={chipClass(active, size, className)}
      {...props}
    />
  )
}

/**
 * A chip that is a page: a champion's roles, each at its own address. A link
 * rather than a button, so the pages it leads to are linked and each can be
 * opened in a new tab; the one on screen is marked current, not pressed.
 */
function ChipLink({
  active,
  size = 'default',
  className,
  ...props
}: React.ComponentProps<typeof Link> & { active: boolean; size?: 'default' | 'sm' }) {
  return (
    <Link
      aria-current={active ? 'page' : undefined}
      data-slot="chip"
      className={chipClass(active, size, className)}
      {...props}
    />
  )
}

export { Chip, ChipGroup, ChipLink }
