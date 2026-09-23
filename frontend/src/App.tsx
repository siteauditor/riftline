import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { SearchIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { TooltipProvider } from '@/components/ui/tooltip'

import SearchBar from './components/SearchBar'
import { api } from './lib/api'

export const PRODUCT_NAME = 'Riftline'

/**
 * App shell.
 *
 * The header carries the search everywhere except the landing page, where the
 * search is the whole point of the view and duplicating it would be noise.
 */
export default function App() {
  const location = useLocation()
  const isHome = location.pathname === '/'

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
  })

  // Says the app has taken the document over. A prerendered page is complete
  // HTML before any script runs, and the browser test must not click into it
  // until it is live: the search form would submit natively and a select
  // would be a button that does nothing.
  useEffect(() => {
    document.documentElement.dataset.hydrated = 'true'
  }, [])

  // The search, from anywhere: Ctrl+K (Cmd+K on a Mac), or the button the
  // header shows where it has no room for the field itself. The dialog is
  // the same search bar the home page has, so there is one search to learn.
  const [searchOpen, setSearchOpen] = useState(false)
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <TooltipProvider>
    <div className="flex min-h-screen flex-col">
      <header className="site-header sticky top-0 z-40 border-b border-line bg-deep/90 backdrop-blur">
        {/* `min-w-0` and a scrollable nav: nothing in this row could shrink,
            so adding a third link pushed the whole document into horizontal
            scroll below about 390px, and the sticky background stopped at the
            viewport edge leaving an unpainted strip. */}
        <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:gap-6">
          <Link
            to="/"
            viewTransition
            className="shrink-0 font-display text-lg font-800 tracking-tight text-ink hover:text-gold-bright"
          >
            <span className="uppercase tracking-[0.06em]">{PRODUCT_NAME}</span>
            <span className="text-accent">.</span>
          </Link>

          <nav className="-mb-px flex min-w-0 flex-shrink items-stretch gap-1 overflow-x-auto text-sm">
            {[
              { to: '/tierlist', label: 'Tier list' },
              { to: '/draft', label: 'Draft' },
              { to: '/items', label: 'Items' },
              { to: '/leaderboards', label: 'Leaderboards' },
              { to: '/groups', label: 'Groups' },
            ].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                viewTransition
                className={({ isActive }) =>
                  `flex h-14 shrink-0 items-center border-b-2 px-2.5 font-display text-[13px] font-600 uppercase tracking-[0.12em] transition-colors ${
                    isActive
                      ? 'border-accent text-accent-bright'
                      : 'border-transparent text-ink-dim hover:text-ink'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          {!isHome && (
            <div className="hidden max-w-sm flex-1 md:block">
              <SearchBar />
            </div>
          )}
          {!isHome && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Search a player"
              onClick={() => setSearchOpen(true)}
              className="md:hidden"
            >
              <SearchIcon />
            </Button>
          )}

          <div className="ml-auto flex items-center gap-4 text-xs text-ink-faint">
            {health?.static_data_version && (
              <span className="eyebrow hidden sm:inline">
                Patch {health.static_data_version}
              </span>
            )}
            {health && !health.riot_key_configured && (
              <span className="rounded-sm border border-loss/40 bg-loss-deep px-2 py-1 text-loss">
                No API key
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <Dialog open={searchOpen} onOpenChange={setSearchOpen}>
        <DialogContent
          showCloseButton={false}
          className="top-[15vh] translate-y-0 gap-0 rounded-[2px] border-line bg-deep p-2 sm:max-w-xl"
        >
          <DialogTitle className="sr-only">Search a player</DialogTitle>
          {searchOpen && <SearchBar size="large" autoFocus onNavigate={() => setSearchOpen(false)} />}
        </DialogContent>
      </Dialog>

      <footer className="border-t border-line-soft py-6">
        <div className="mx-auto max-w-[1280px] space-y-2 px-4 text-xs leading-relaxed text-ink-faint">
          <p>
            <Link to="/method" className="underline decoration-line underline-offset-2 hover:text-ink-dim">
              How our numbers are made
            </Link>
            : the score's weights and how well they track wins, the win-chance model's accuracy,
            and the rules behind the death review.
          </p>
          <p>
            {PRODUCT_NAME} isn't endorsed by Riot Games and doesn't reflect the views or
            opinions of Riot Games or anyone officially involved in producing or managing
            League of Legends.
          </p>
        </div>
      </footer>
    </div>
    </TooltipProvider>
  )
}
