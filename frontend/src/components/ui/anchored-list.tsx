import type { ReactElement, ReactNode, RefObject } from 'react'

import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

/**
 * A list that drops under a field: a Radix popover anchored to the field and
 * portalled to the body.
 *
 * Drawn in place, a list was clipped by whatever held the field (the home hero
 * hides its overflow for the splash art and cut the search list off after three
 * rows) and sat at 94% over the next field, whose text read through it (both
 * seen 2026-09-23). Here the ground is opaque, focus stays in the field (no
 * auto focus either way, and no dialog role: the field owns the options), and a
 * press on the field itself is not an outside press, which would close the list
 * and reopen it in one click. `anchorRef` is read only in that handler, never
 * during render.
 */
export function AnchoredList({
  open,
  onDismiss,
  anchor,
  anchorRef,
  className,
  children,
}: {
  open: boolean
  onDismiss: () => void
  /** The field, with `ref={anchorRef}` on it. */
  anchor: ReactElement
  anchorRef: RefObject<HTMLElement | null>
  className?: string
  children: ReactNode
}) {
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) onDismiss()
      }}
    >
      <PopoverAnchor asChild>{anchor}</PopoverAnchor>
      <PopoverContent
        align="start"
        sideOffset={4}
        role="presentation"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => e.preventDefault()}
        onInteractOutside={(e) => {
          if (anchorRef.current?.contains(e.target as Node)) e.preventDefault()
        }}
        className={cn(
          'w-(--radix-popover-trigger-width) overflow-hidden rounded-lg border-line bg-panel p-0 text-ink shadow-[0_18px_44px_-12px_rgb(0_0_0/0.85)]',
          className,
        )}
      >
        {children}
      </PopoverContent>
    </Popover>
  )
}
