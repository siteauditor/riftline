import { useEffect, useState, type ReactNode } from 'react'

import { ApiError } from '../lib/api'

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

/** Skeleton rows sized to the real match list, so the layout does not jump. */
export function MatchListSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-1.5" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-[86px] animate-pulse border-b border-l-[3px] border-line-soft border-l-line bg-panel/40"
          style={{ animationDelay: `${i * 70}ms` }}
        />
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

  let title = 'Something went wrong'
  let body = api?.message ?? 'An unexpected error occurred.'
  let action: ReactNode = null

  if (api?.kind === 'not_found' && context) {
    title = 'No player found'
    body = `${context} doesn't exist on that region. Check the tag after the # and the region, since the same name can exist on several regions with different tags.`
  } else if (api?.kind === 'not_found') {
    // Not every 404 is a missing player. The meta and draft endpoints answer
    // 404 for "not enough data yet" and their own message already says what to
    // do about it, so pass it through instead of guessing.
    title = 'Nothing to show yet'
    body = api.message
  } else if (api?.kind === 'rate_limited') {
    title = 'Riot rate limit reached'
    body =
      'A development key allows 100 requests every 2 minutes, and this lookup used them up. It clears on its own.'
    action = api.retryAfter ? (
      <p className="text-sm text-ink-dim">
        Try again in <Countdown key={api.retryAfter} seconds={api.retryAfter} />
      </p>
    ) : null
  } else if (api?.kind === 'expired_key') {
    title = 'The API key needs renewing'
    body =
      'Riot development keys expire every 24 hours. Generate a new one at developer.riotgames.com, put it in backend/.env as RIOT_API_KEY, and restart the server.'
  } else if (api?.kind === 'gone') {
    title = 'Riot removed this endpoint'
    body = api.message
  } else if (api?.kind === 'unavailable') {
    // Distinct from expired_key on purpose: the key is fine, so telling anyone
    // to regenerate it would send them after the wrong problem.
    title = 'Not available'
    body = api.message
  } else if (api?.kind === 'upstream') {
    title = "Riot's API isn't responding"
    body = "This is on Riot's side. It usually clears within a few minutes."
  }

  return (
    <div className="accent-edge rounded-r-sm border-y border-r border-line bg-panel px-5 py-6">
      <h2 className="display text-xl font-700 text-ink">{title}</h2>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-ink-dim">{body}</p>
      {action && <div className="mt-3">{action}</div>}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-4 rounded-sm border border-line bg-raised px-3 py-1.5 text-sm font-500 text-ink transition-colors hover:border-gold hover:text-gold-bright"
        >
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-sm border border-dashed border-line px-5 py-10 text-center">
      <p className="display text-lg font-600 text-ink">{title}</p>
      <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-ink-dim">{body}</p>
    </div>
  )
}
