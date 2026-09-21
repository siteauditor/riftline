import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/**
 * Numbered pages, as real links.
 *
 * The leaderboard had only Previous and Next under fifty rows, with no page
 * count although the response knows the total, so rank 800 was sixteen clicks
 * away. Each page is a link to its own URL: it can be opened in a new tab,
 * and following one adds a history entry, so back returns to the page before.
 */
export default function Pager({
  page,
  pageCount,
  hrefFor,
  children,
  aside,
}: {
  page: number
  pageCount: number
  /** The link for a page, usually the current search with `page` changed. */
  hrefFor: (page: number) => string
  /** Shown beside the numbers, e.g. which ranks the page holds. */
  children?: ReactNode
  /** A control beside the page count, e.g. a jump box. */
  aside?: ReactNode
}) {
  if (pageCount <= 1 && page <= 1) {
    return children ? <div className="text-xs text-ink-faint">{children}</div> : null
  }
  const last = Math.max(pageCount, 1)
  return (
    <nav
      aria-label="Pages"
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-xs"
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <span className="tnum text-ink-faint">
          Page {page} of {last}
          {children && <span>, {children}</span>}
        </span>
        {aside}
      </div>
      <div className="flex items-center gap-1">
        <Step to={page > 1 ? hrefFor(Math.min(page - 1, last)) : null} label="Previous page">
          <span aria-hidden className="sm:hidden">&lsaquo;</span>
          <span className="hidden sm:inline">Previous</span>
        </Step>
        {pageWindow(page, last).map((n, i) =>
          n === null ? (
            <span key={`gap-${i}`} aria-hidden className="px-1 text-ink-faint">
              &hellip;
            </span>
          ) : n === page ? (
            <span
              key={n}
              aria-current="page"
              className="tnum min-w-8 rounded-sm border border-gold px-2 py-1.5 text-center font-600 text-gold-bright"
            >
              {n}
            </span>
          ) : (
            <Link
              key={n}
              to={hrefFor(n)}
              aria-label={`Page ${n}`}
              className="tnum min-w-8 rounded-sm border border-line px-2 py-1.5 text-center text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
            >
              {n}
            </Link>
          ),
        )}
        <Step to={page < last ? hrefFor(page + 1) : null} label="Next page">
          <span aria-hidden className="sm:hidden">&rsaquo;</span>
          <span className="hidden sm:inline">Next</span>
        </Step>
      </div>
    </nav>
  )
}

function Step({ to, label, children }: { to: string | null; label: string; children: ReactNode }) {
  const className = 'min-w-8 rounded-sm border px-2.5 py-1.5 text-center transition-colors'
  if (to === null) {
    return (
      <span aria-disabled className={`${className} border-line text-ink-dim opacity-35`}>
        {children}
      </span>
    )
  }
  return (
    <Link
      to={to}
      aria-label={label}
      className={`${className} border-line text-ink-dim hover:border-gold hover:text-gold-bright`}
    >
      {children}
    </Link>
  )
}

/**
 * The first and last page, and the current one with a neighbour each side.
 * A gap of one page shows that page rather than an ellipsis standing for it.
 * Seven entries at most, which fits a 390px phone with the arrows.
 */
function pageWindow(page: number, last: number): (number | null)[] {
  const wanted = new Set([1, last, page - 1, page, page + 1].filter((n) => n >= 1 && n <= last))
  const sorted = [...wanted].sort((a, b) => a - b)
  const out: (number | null)[] = []
  sorted.forEach((n, i) => {
    const previous = sorted[i - 1]
    if (previous !== undefined && n - previous === 2) out.push(previous + 1)
    else if (previous !== undefined && n - previous > 2) out.push(null)
    out.push(n)
  })
  return out
}
