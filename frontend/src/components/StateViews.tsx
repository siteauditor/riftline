import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useEffect, useState, type ReactNode } from 'react'

import { ApiError } from '../lib/api'
import { operatorHint, publicErrorText } from '../lib/errors'

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-ink-dim">
      <span
        aria-hidden
        className="size-4 animate-spin rounded-full border-2 border-line border-t-gold"
      />
      {label && <span>{label}</span>}
    </div>
  )
}

/**
 * Placeholder match rows.
 *
 * It traces the real row's grid, `[104px auto 1fr auto]`, and the shapes inside
 * each column, so the list that arrives lands where the placeholder stood and
 * nothing jumps. Six blank bars did hold the height, but they said nothing
 * about what was coming and their staggered pulse travelled down the page like
 * water. The breathing is on the wrapper here, so all of it moves as one.
 */
export function MatchListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-1.5" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="border-b border-l-[3px] border-line-soft border-l-line bg-panel/40"
        >
          <div className="grid grid-cols-1 gap-x-4 gap-y-3 px-3 py-3 sm:grid-cols-[104px_auto_1fr_auto]">
            {/* Queue, time, result and duration. Not the lobby rank badge: a
                row only grows that once its lobby has been measured, and a
                profile being loaded for the first time is exactly the case
                this stands in for. */}
            <div className="space-y-1.5">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-2.5 w-12" />
              <Skeleton className="h-2.5 w-16" />
            </div>

            {/* Champion, then the two 22px stacks of spells and runes */}
            <div className="flex items-center gap-2">
              <Skeleton className="size-12 shrink-0" />
              <div className="flex flex-col gap-0.5">
                <Skeleton className="size-[22px]" />
                <Skeleton className="size-[22px]" />
              </div>
              <div className="flex flex-col gap-0.5">
                <Skeleton className="size-[22px] rounded-full" />
                <Skeleton className="size-[22px] rounded-full" />
              </div>
            </div>

            {/* KDA and the Riftline score, then the two stat pairs and the
                item row, in the same flex-wrap the row uses. */}
            <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
              {/* KDA at 22px display, its ratio, and the score with its
                  placement. Laning is left out for the same reason as the rank
                  badge: it needs a timeline that has not been fetched yet.
                  Measured against a freshly loaded row, 118px, which is what a
                  placeholder is standing in front of. */}
              <div className="space-y-1.5">
                <Skeleton className="h-5 w-24" />
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-3.5 w-20" />
              </div>
              <div className="grid grid-cols-2 gap-x-5 gap-y-1 pt-0.5 sm:grid-cols-1">
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="h-2.5 w-14" />
              </div>
              <div className="grid grid-cols-2 gap-x-5 gap-y-1 pt-0.5 sm:grid-cols-1">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="h-2.5 w-12" />
              </div>
              <div className="flex gap-1 pt-0.5">
                {Array.from({ length: 6 }).map((_, n) => (
                  <div key={n} className="skeleton size-[26px]" />
                ))}
                <Skeleton className="size-[26px] rounded-full" />
              </div>
            </div>

            {/* Ten names in two columns, only on the wide layout, exactly as
                the row itself hides them when narrow. */}
            <div className="hidden grid-cols-2 gap-x-4 gap-y-1 lg:grid">
              {Array.from({ length: 10 }).map((_, n) => (
                <div key={n} className="flex items-center gap-1.5">
                  <Skeleton className="size-4 shrink-0" />
                  <Skeleton className="h-2 w-16" />
                </div>
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Counts down from `seconds`.
 *
 * State is seeded once from the prop and only ever changed by the interval, so
 * render stays pure and no effect writes state. Callers pass `key={seconds}` to
 * restart it when a new cooldown arrives, which is cheaper and clearer than
 * syncing prop into state.
 */
function Countdown({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(() => Math.ceil(seconds))

  useEffect(() => {
    const id = setInterval(() => setLeft((n) => (n > 0 ? n - 1 : 0)), 1000)
    return () => clearInterval(id)
  }, [])

  return <span className="tnum">{left}s</span>
}

/**
 * Failure states.
 *
 * Each one says what happened and what to do about it. A rate limit on a
 * development key is a normal, timed wait rather than an error, and an expired
 * key is a two-minute fix, so neither is dressed up as a crash.
 */
export function ErrorView({
  error,
  onRetry,
  context,
}: {
  error: unknown
  onRetry?: () => void
  context?: string
}) {
  const api = error instanceof ApiError ? error : null
  const { title, body } = publicErrorText(error, context)
  const hint = operatorHint(error)
  const action: ReactNode =
    api?.kind === 'rate_limited' && api.retryAfter ? (
      <p className="text-sm text-ink-dim">
        Try again in <Countdown key={api.retryAfter} seconds={api.retryAfter} />
      </p>
    ) : null

  return (
    <div className="accent-edge rounded-r-lg border-y border-r border-line bg-panel px-5 py-6">
      <h2 className="display text-xl font-700 text-ink">{title}</h2>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-dim">{body}</p>
      {hint && <p className="mt-2 max-w-prose text-xs text-ink-faint">Development: {hint}</p>}
      {action && <div className="mt-3">{action}</div>}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-4 text-ink">
          Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  /** The way out of the empty state, when there is one. */
  action?: ReactNode
}) {
  return (
    <div className="rounded-sm border border-dashed border-line px-5 py-10 text-center">
      <p className="display text-lg font-600 text-ink">{title}</p>
      <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-ink-dim">{body}</p>
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

/** Rows of a list or table, traced roughly: a tile, a name, then figures. */
export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 border-b border-line-soft px-3 py-2.5">
          <Skeleton className="size-10 shrink-0 rounded-md" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-32 max-w-[40%]" />
            <Skeleton className="h-2.5 w-20" />
          </div>
          <Skeleton className="h-3 w-16" />
          <Skeleton className="hidden h-3 w-12 sm:block" />
          <Skeleton className="hidden h-3 w-12 md:block" />
          <Skeleton className="hidden h-3 w-12 lg:block" />
        </div>
      ))}
    </div>
  )
}

/** A grid of tiles with a label under each: the item guide, a skin board. */
export function GridSkeleton({ items = 12 }: { items?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-hidden>
      {Array.from({ length: items }).map((_, i) => (
        <div key={i} className="frame flex items-center gap-3 p-3">
          <Skeleton className="size-10 shrink-0 rounded-md" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-3/4" />
            <Skeleton className="h-2.5 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * A profile before its first answer: the header band with its icon and
 * name, the rank card and play style on the rail, and match rows in the
 * feed, in the places the real ones land.
 */
export function ProfileSkeleton() {
  // The profile's own layout (`ProfileHeader`, then the games first): a
  // compact header, the form strip, the filters and the rows, with the rail
  // on the left from lg and below the games on a phone.
  return (
    <div aria-hidden>
      <div className="border-b border-line-soft">
        <div className="mx-auto max-w-[1280px] space-y-3 px-4 py-4 sm:py-6">
          <div className="flex items-center gap-3 sm:gap-4">
            <Skeleton className="size-10 shrink-0 rounded-md sm:size-16" />
            <div className="space-y-2">
              <Skeleton className="h-7 w-56 max-w-[60vw] sm:h-9" />
              <Skeleton className="h-4 w-72 max-w-[70vw]" />
            </div>
          </div>
          <Skeleton className="h-3 w-80 max-w-[85vw]" />
        </div>
      </div>
      <div className="mx-auto grid max-w-[1280px] gap-5 px-4 pt-4 sm:pt-6 lg:grid-cols-[280px_1fr]">
        <div className="min-w-0 space-y-4 lg:col-start-2 lg:row-start-1">
          <Skeleton className="h-28 rounded-lg sm:h-32" />
          <Skeleton className="h-8 w-2/3" />
          <MatchListSkeleton rows={5} />
        </div>
        <div className="space-y-4 lg:col-start-1 lg:row-start-1">
          <Skeleton className="h-72 rounded-lg" />
          <Skeleton className="h-40 rounded-lg" />
        </div>
      </div>
    </div>
  )
}

/** A whole page before its first answer: the header band, then rows. */
export function PageSkeleton() {
  return (
    <div aria-hidden>
      <div className="border-b border-line-soft">
        <div className="mx-auto max-w-[1280px] px-4 py-7 sm:py-9">
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-3 h-9 w-72 max-w-[70vw]" />
          <Skeleton className="mt-3 h-3.5 w-96 max-w-[80vw]" />
        </div>
      </div>
      <div className="mx-auto max-w-[1280px] px-4 py-6">
        <TableSkeleton rows={8} />
      </div>
    </div>
  )
}

/** Lines of text, ragged like a paragraph. */
export function ProseSkeleton({ lines = 6 }: { lines?: number }) {
  const widths = [92, 85, 96, 70, 88, 60]
  return (
    <div className="space-y-2.5" aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-3.5" style={{ width: `${widths[i % widths.length]}%` }} />
      ))}
    </div>
  )
}
