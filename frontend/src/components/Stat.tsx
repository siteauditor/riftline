import type { ReactNode } from 'react'

/**
 * A labelled figure, the way a broadcast graphic sets one: a tracked-out label
 * above, the number large and condensed below.
 *
 * Every page here has a handful of figures that are the point of the page, and
 * they used to sit at 13px in the middle of a row. This is the one shared way
 * to make one of them the subject.
 */
export function Stat({
  label,
  value,
  sub,
  color,
  title,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  color?: string
  title?: string
}) {
  return (
    <div title={title} className="min-w-0">
      <p className="eyebrow truncate">{label}</p>
      <p
        className="tnum display mt-0.5 text-2xl font-700 leading-none text-ink sm:text-[28px]"
        style={color ? { color } : undefined}
      >
        {value}
      </p>
      {sub && <p className="mt-1 truncate text-[11px] text-ink-faint">{sub}</p>}
    </div>
  )
}

/**
 * A row of them, divided by hairlines. Scrolls rather than wraps on a phone,
 * because a stat strip that reflows into two ragged rows stops reading as a
 * strip at all.
 */
export function StatStrip({ children }: { children: ReactNode }) {
  return (
    <div className="frame flex divide-x divide-line overflow-x-auto">
      {children}
    </div>
  )
}

export function StatCell({ children }: { children: ReactNode }) {
  return <div className="min-w-[7.5rem] shrink-0 px-4 py-3 sm:min-w-0 sm:flex-1">{children}</div>
}

/**
 * The section marker: an eyebrow, a title and a rule that runs to the edge.
 * The rule is what turns a heading into a band, and bands are what a broadcast
 * package is made of.
 */
export function SectionTitle({
  eyebrow,
  title,
  aside,
}: {
  eyebrow?: string
  title: ReactNode
  aside?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-1 border-b border-line pb-2">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2 className="display text-xl font-700 uppercase tracking-wide text-ink sm:text-2xl">
          {title}
        </h2>
      </div>
      {aside && <div className="text-sm text-ink-dim">{aside}</div>}
    </div>
  )
}
