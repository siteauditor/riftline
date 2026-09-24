import { useEffect, useState, type CSSProperties } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronDownIcon, SearchIcon } from 'lucide-react'
import { Toaster } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { TooltipProvider } from '@/components/ui/tooltip'

import Hint from './components/Hint'
import SearchBar from './components/SearchBar'
import { api } from './lib/api'

export const PRODUCT_NAME = 'Riftline'

/** The header's pages, in the row on a wide screen and in the menu on a narrow one. */
const NAV = [
  { to: '/tierlist', label: 'Tier list' },
  { to: '/champions', label: 'Champions' },
  { to: '/draft', label: 'Draft' },
  { to: '/items', label: 'Items' },
  { to: '/leaderboards', label: 'Leaderboards' },
  { to: '/groups', label: 'Groups' },
]

/**
 * App shell.
 *
 * The header carries the search everywhere except the landing page, where the
 * search is the whole point of the view and duplicating it would be noise.
 */
export default function App() {
  const location = useLocation()
  const isHome = location.pathname === '/'

  // Every five minutes, not every thirty seconds: it carries the patch and
  // whether the Riot key works, which change a few times a day, and at 30 s
  // each open tab asked 120 times an hour.
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 5 * 60_000,
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
      <header className="site-header glass sticky top-0 z-40 border-b border-white/[0.06]">
        {/* Below lg the pages are one menu (SiteMenu): the row does not fit
            beside the search. `min-w-0` and the nav's own scroll stay as a
            guard, because a row that could not shrink once pushed the whole
            document into horizontal scroll and left the sticky background
            short of the viewport edge. */}
        <div className="mx-auto flex h-14 max-w-[1280px] items-center gap-3 px-4 sm:gap-6">
          <Link
            to="/"
            viewTransition
            className="shrink-0 font-display text-lg font-800 tracking-tight text-ink hover:text-gold-bright"
          >
            <span className="uppercase tracking-[0.06em]">{PRODUCT_NAME}</span>
            <span className="text-accent">.</span>
          </Link>

          <SiteMenu pathname={location.pathname} />
          <nav
            aria-label="Pages"
            className="-mx-1 -my-1 hidden min-w-0 flex-shrink items-center gap-1 overflow-x-auto px-1 py-1 text-sm lg:flex"
          >
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                viewTransition
                className={({ isActive }) =>
                  `flex h-8 shrink-0 items-center rounded-full px-3 font-display text-[13px] font-600 uppercase tracking-[0.12em] transition-colors ${
                    isActive
                      ? 'bg-accent/12 text-accent-bright'
                      : 'text-ink-dim hover:bg-white/[0.05] hover:text-ink'
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
            {/* Not from lg to xl: there the page row and the search need its
                room, and at 1024 px the row showed 443 px of its 502. */}
            {health?.static_data_version && (
              <span className="eyebrow hidden sm:inline lg:hidden xl:inline">
                Patch {health.static_data_version}
              </span>
            )}
            {/* Riot refused the key (or there is none): searches and live
                pages will fail until it is rotated, and saying so up front
                beats letting each visitor find out from a lookup. The exact
                state is for whoever runs the server. */}
            {health && (!health.riot_key_configured || health.riot_key_ok === false) && (
              <Hint
                text={
                  import.meta.env.DEV
                    ? health.riot_key_configured
                      ? 'Riot rejected the API key. Put a new one in backend/.env and restart.'
                      : 'RIOT_API_KEY is not set in backend/.env.'
                    : 'Riftline cannot ask Riot for live data right now. Stored pages still work.'
                }
              >
                <span
                  tabIndex={0}
                  className="rounded-sm border border-loss/40 bg-loss-deep px-2 py-1 text-loss"
                >
                  Live data paused
                </span>
              </Hint>
            )}
          </div>
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      {/* Toasts: what an action did, said once, out of the way. The colours
          are the site's own, through sonner's variables. */}
      <Toaster
        position="bottom-right"
        offset={16}
        toastOptions={{ className: 'font-sans' }}
        style={
          {
            '--normal-bg': 'var(--color-panel)',
            '--normal-text': 'var(--color-ink)',
            '--normal-border': 'var(--color-line)',
            '--success-bg': 'var(--color-panel)',
            '--success-text': 'var(--color-accent-bright)',
            '--success-border': 'color-mix(in srgb, var(--color-accent) 40%, var(--color-line))',
            '--error-bg': 'var(--color-panel)',
            '--error-text': 'var(--color-loss)',
            '--error-border': 'color-mix(in srgb, var(--color-loss) 40%, var(--color-line))',
            '--border-radius': 'var(--radius-lg)',
          } as CSSProperties
        }
      />

      <Dialog open={searchOpen} onOpenChange={setSearchOpen}>
        <DialogContent
          showCloseButton={false}
          className="glow top-[15vh] translate-y-0 gap-0 rounded-lg border-white/10 bg-deep/95 p-2 backdrop-blur-xl sm:max-w-xl"
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

/**
 * The header's pages below the width that holds them all, as one menu named
 * after the page on screen. The row used to scroll sideways under the logo:
 * a 412 px phone showed 249 px of its 502, and Leaderboards and Groups sat
 * past an edge nothing marked (2026-09-24).
 */
function SiteMenu({ pathname }: { pathname: string }) {
  const current = NAV.find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={`flex h-8 min-w-0 cursor-pointer items-center gap-1.5 rounded-full px-3 font-display text-[13px] font-600 uppercase tracking-[0.12em] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent/60 lg:hidden ${
          current ? 'bg-accent/12 text-accent-bright' : 'text-ink-dim hover:bg-white/[0.05] hover:text-ink'
        }`}
      >
        <span className="truncate">
          {current ? (
            <>
              <span className="sr-only">Menu, now on </span>
              {current.label}
            </>
          ) : (
            'Menu'
          )}
        </span>
        <ChevronDownIcon aria-hidden className="size-4 shrink-0" />
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        {NAV.map((item) => (
          <DropdownMenuItem key={item.to} asChild>
            {/* A string class, not NavLink's function: the menu item merges
                its own class into the link's. NavLink marks the current page
                with aria-current, which is what colours it. */}
            <NavLink
              to={item.to}
              viewTransition
              className="font-display text-[13px] font-600 uppercase tracking-[0.12em] text-ink-dim aria-[current=page]:text-accent-bright"
            >
              {item.label}
            </NavLink>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
