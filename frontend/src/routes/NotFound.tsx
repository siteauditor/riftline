import { Link, isRouteErrorResponse, useLocation, useRouteError } from 'react-router-dom'

import SearchBar from '../components/SearchBar'
import { PRODUCT_NAME } from '../App'

/**
 * The two views nobody plans for, which a deployed site shows anyway.
 *
 * Without them React Router falls back to its own developer screen: a bare
 * "Unexpected Application Error!" over "Hey developer" and a note about
 * errorElement props. Fine on localhost, addressed to the wrong person in
 * production, and the shape of it (no header, no search, no way back) leaves a
 * visitor who mistyped a URL with nothing to click.
 */

const EXITS = [
  { to: '/tierlist', label: 'Champion tier list' },
  { to: '/leaderboards', label: 'Leaderboards' },
  { to: '/draft', label: 'Draft helper' },
]

/** An address that is not a page. Rendered inside the app shell. */
export default function NotFound() {
  const { pathname } = useLocation()

  return (
    <div className="mx-auto max-w-[1280px] px-4 py-16">
      <p className="font-display text-sm font-600 tracking-wide text-gold">404</p>
      <h1 className="display mt-2 text-3xl font-800 text-ink sm:text-4xl">
        There is no page at that address.
      </h1>
      <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
        <span className="tnum break-all text-ink">{pathname}</span> is not one of ours.
        A profile lives at <span className="text-ink">/summoner/euw1/Name/TAG</span>, so
        the quickest way to what you wanted is probably to search for the player.
      </p>

      <div className="mt-6 max-w-md">
        <SearchBar />
      </div>

      <nav className="mt-8 flex flex-wrap gap-2">
        {EXITS.map((exit) => (
          <Link
            key={exit.to}
            to={exit.to}
            className="rounded-sm border border-line bg-raised px-3 py-1.5 text-sm font-500 text-ink transition-colors hover:border-gold hover:text-gold-bright"
          >
            {exit.label}
          </Link>
        ))}
      </nav>
    </div>
  )
}

/**
 * A crash, or a routing failure that happened before the shell mounted.
 *
 * It carries its own minimal header rather than reusing the app shell, because
 * the shell is one of the things that can have thrown. The message names what
 * we know and no more: guessing at a cause here would be a guess in the one
 * place a visitor has least reason to trust us.
 */
export function RouteError() {
  const error = useRouteError()

  const detail = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : null

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line-soft">
        <div className="mx-auto flex h-14 max-w-[1280px] items-center px-4">
          <Link
            to="/"
            className="font-display text-lg font-800 tracking-tight text-ink hover:text-gold-bright"
          >
            {PRODUCT_NAME}
            <span className="text-gold">.</span>
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-16">
        <div className="accent-edge max-w-prose rounded-r-sm border-y border-r border-line bg-panel px-5 py-6">
          <h1 className="display text-xl font-700 text-ink">This page failed to load</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-dim">
            Something in the page itself broke, so there is nothing useful to show here.
            Reloading usually fixes it; the rest of the site is unaffected.
          </p>
          {detail && (
            <p className="mt-3 rounded-sm border border-line-soft bg-deep px-3 py-2 font-mono text-xs break-words text-ink-faint">
              {detail}
            </p>
          )}
          <div className="mt-4 flex gap-2">
            <button
              onClick={() => window.location.reload()}
              className="rounded-sm border border-line bg-raised px-3 py-1.5 text-sm font-500 text-ink transition-colors hover:border-gold hover:text-gold-bright"
            >
              Reload
            </button>
            <Link
              to="/"
              className="rounded-sm border border-line bg-raised px-3 py-1.5 text-sm font-500 text-ink transition-colors hover:border-gold hover:text-gold-bright"
            >
              Start again
            </Link>
          </div>
        </div>
      </main>
    </div>
  )
}
