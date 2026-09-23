import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { Slot } from 'radix-ui'

import { cn } from '@/lib/utils'

/**
 * The button, in the four ways the site draws one: teal, lit from below,
 * for the one action on a page (`default`, the search button); a glass
 * hairline that warms to the accent for the rest (`outline`, the Update and
 * Load-more buttons); bare text that lights up (`ghost`); and a link. The
 * corners come from the radius tokens.
 */
const buttonVariants = cva(
  'inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-md text-sm font-500 whitespace-nowrap transition-[color,background-color,border-color,box-shadow,transform] duration-150 outline-none focus-visible:ring-2 focus-visible:ring-accent/60 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:active:translate-y-0 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=size-])]:size-4',
  {
    variants: {
      variant: {
        default:
          'bg-gradient-to-r from-accent to-accent-bright font-display font-700 tracking-[0.12em] text-deep uppercase shadow-[0_8px_24px_-10px_var(--color-accent)] hover:shadow-[0_10px_30px_-8px_var(--color-accent)] hover:brightness-110',
        outline:
          'border border-white/10 bg-white/[0.03] text-ink-dim hover:border-accent/50 hover:bg-white/[0.06] hover:text-ink',
        secondary: 'bg-raised text-ink hover:bg-line',
        ghost: 'text-ink-dim hover:bg-white/[0.06] hover:text-ink',
        link: 'text-gold-bright underline decoration-line underline-offset-2 hover:decoration-gold-bright',
      },
      size: {
        default: 'h-9 px-4 py-2 has-[>svg]:px-3',
        xs: 'h-6 gap-1 px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*=size-])]:size-3',
        sm: 'h-8 gap-1.5 px-3 has-[>svg]:px-2.5',
        lg: 'h-10 px-6 has-[>svg]:px-4',
        icon: 'size-9',
        'icon-xs': 'size-6 [&_svg:not([class*=size-])]:size-3',
        'icon-sm': 'size-8',
        'icon-lg': 'size-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

function Button({
  className,
  variant = 'default',
  size = 'default',
  asChild = false,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : 'button'

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
