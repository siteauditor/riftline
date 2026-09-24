import { useId } from 'react'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

/**
 * A labelled select: the label, then the control, on one line.
 *
 * Every filter on the site is one of these, so they share one shape and one
 * look. Radix refuses an empty item value, so a caller with an "any" option
 * gives it a word ('all', 'latest') and maps it back to null itself.
 */
export default function SelectField({
  label,
  ariaLabel,
  value,
  onValueChange,
  options,
  disabled,
  className,
  labelClassName,
  triggerClassName,
  contentClassName,
  bare = false,
}: {
  label?: string
  /** For a select with no visible label. */
  ariaLabel?: string
  value: string
  onValueChange: (value: string) => void
  options: SelectOption[]
  disabled?: boolean
  className?: string
  /** For a label that reads only to a screen reader on a narrow screen
   *  (`max-sm:sr-only`), where the control's own value says enough. */
  labelClassName?: string
  triggerClassName?: string
  contentClassName?: string
  /** No border and no ground: for a select set into a frame of its own, like the search bar's region. */
  bare?: boolean
}) {
  const id = useId()
  return (
    <div className={cn('flex items-center gap-2 text-ink-dim', className)}>
      {label && (
        <label htmlFor={id} className={cn('text-xs text-ink-faint', labelClassName)}>
          {label}
        </label>
      )}
      <Select
        value={value}
        // Only a value this select offers is passed on. Inside a form, Radix
        // keeps a hidden native select in step with the value, and a value
        // set before the options have registered (the search bar adopting
        // the remembered region right after hydration) leaves that select on
        // "" and fires its change event: the region became empty, the label
        // went blank and a search went to /summoner//name (seen 2026-09-23).
        onValueChange={(next) => {
          if (options.some((o) => o.value === next)) onValueChange(next)
        }}
        disabled={disabled}
      >
        <SelectTrigger
          id={id}
          size="sm"
          aria-label={ariaLabel}
          className={cn(bare && 'h-full rounded-none border-0 bg-transparent', triggerClassName)}
        >
          {/* The label as the value node's own child: Radix otherwise fills
              it from the selected item after mount, so a prerendered page
              would show an empty control until the script ran. */}
          <SelectValue>{options.find((o) => o.value === value)?.label}</SelectValue>
        </SelectTrigger>
        <SelectContent className={contentClassName}>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
