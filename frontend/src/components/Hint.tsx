import type { ReactElement, ReactNode } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

/**
 * An explanation on hover and on focus, in place of a `title` attribute.
 *
 * The child is the element itself (a badge, a figure, a button); it is
 * given the trigger's handlers rather than wrapped in another box, so the
 * layout it sits in does not change. An element that is not naturally
 * focusable should carry `tabIndex={0}`, or the keyboard never sees the
 * hint.
 */
export default function Hint({ text, children }: { text: ReactNode; children: ReactElement }) {
  if (!text) return children
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  )
}
