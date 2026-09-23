import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import PositionIcon from '../components/PositionIcon'
import { EmptyState, ErrorView, GridSkeleton } from '../components/StateViews'
import { POSITIONS, type ChampionIndexEntry } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'
import { queries } from '../lib/queries'
import { heads } from '../lib/seo'
import {
  championPath,
  foldName,
  positionParam,
  useHydratedSearchParams,
  useSearchText,
  withParams,
} from '../lib/searchParams'
import { Button } from '@/components/ui/button'
import { Chip, ChipGroup } from '@/components/ui/chips'

/**
 * Every champion, A to Z, with the roles each is played in.
 *
 * The tier list ranks the champions with twenty games in a role, so a
 * champion under that, or one too new to have been played, could only be
 * reached by typing its name into a search. This lists them all, and names
 * each role with a page of its own.
 */
export default function Champions() {
  const [search, setSearch] = useHydratedSearchParams()
  const [query, setQuery] = useSearchText('q', 120)
  const needle = foldName(query)
  const position = positionParam(search.get('position'))
  const setPosition = (next: string | null) =>
    setSearch((prev) => withParams(prev, { position: next }), { replace: true })

  const index = useQuery({ ...queries.championIndex(), staleTime: 10 * 60 * 1000 })
  const data = index.data
  const floor = data?.role_min_games ?? 20

  const all = data?.champions ?? []
  const shown = all.filter(
    (entry) =>
      (!needle || foldName(entry.champion.name).includes(needle)) &&
      (!position || namedRoles(entry, floor).some((p) => p.position === position)),
  )

  return (
    <div>
      <Head {...heads.champions(data?.patch)} />
      <ArtHeader>
        <p className="eyebrow">{data?.patch ? `Patch ${data.patch}, ranked solo` : "Summoner's Rift"}</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Champions
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          Every champion, A to Z, with the roles each is played in. Open one for its builds, runes
          and matchups in its main role, or a role for that role's own page.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-line-soft pb-3 text-sm">
          <label className="flex items-center gap-2">
            <span className="text-xs text-ink-faint">Find</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Type a champion's name"
              className="control h-8 w-52 text-sm placeholder:text-ink-faint"
            />
          </label>
          {data?.patch && (
            <ChipGroup label="Role" className="gap-x-1 gap-y-1">
              <Chip active={position === null} onClick={() => setPosition(null)}>
                <PositionIcon position="ALL" className="size-4" />
                All
              </Chip>
              {POSITIONS.map((p) => (
                <Chip key={p.id} active={position === p.id} onClick={() => setPosition(p.id)}>
                  <PositionIcon position={p.id} className="size-4" />
                  {p.label}
                </Chip>
              ))}
            </ChipGroup>
          )}
          {data && (
            <span className="tnum ml-auto text-xs text-ink-faint">
              {shown.length === all.length ? `${all.length} champions` : `${shown.length} of ${all.length} shown`}
            </span>
          )}
        </div>

        {position && data?.patch && (
          <p className="mt-3 max-w-prose text-xs leading-relaxed text-ink-faint">
            Champions with {floor} or more {positionLabel(position).toLowerCase()} games on patch {data.patch},
            or whose games are mostly there. Each opens on that role.
          </p>
        )}

        {index.isLoading ? (
          <div className="py-8">
            <GridSkeleton />
          </div>
        ) : index.isError ? (
          <div className="mt-6">
            <ErrorView error={index.error} onRetry={() => index.refetch()} />
          </div>
        ) : shown.length === 0 ? (
          <div className="mt-6">
            <EmptyState
              title="No champion matches that"
              body={
                position
                  ? `No champion${needle ? ' by that name' : ''} has ${floor} ${positionLabel(position).toLowerCase()} games on patch ${data?.patch} yet.`
                  : 'No champion has a name like that.'
              }
              action={
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setQuery('')
                    setPosition(null)
                  }}
                >
                  Show every champion
                </Button>
              }
            />
          </div>
        ) : (
          <ul className="mt-5 grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-x-3 gap-y-1">
            {shown.map((entry) => (
              <ChampionCard key={entry.champion.id} entry={entry} floor={floor} position={position} patch={data?.patch} />
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

/**
 * The roles an entry names: each with the sample at which a role gets a page
 * of its own, and the main role whatever its games, so a champion with any
 * games says where they were.
 */
function namedRoles(entry: ChampionIndexEntry, floor: number) {
  return entry.positions.filter((p, i) => i === 0 || p.games >= floor)
}

function ChampionCard({
  entry,
  floor,
  position,
  patch,
}: {
  entry: ChampionIndexEntry
  floor: number
  position: string | null
  patch?: string | null
}) {
  const { champion } = entry
  const main = entry.positions[0]?.position
  // The main role's page is the bare path; its role path points there.
  const pathFor = (role: string | null) => championPath(champion, role === main ? null : role)
  const roles = namedRoles(entry, floor)
  return (
    // The name's link is stretched over the card, as the tier list's rows
    // are, and the role links sit above it: a link cannot hold another.
    <li className="lift relative flex items-center gap-3 px-2 py-2">
      {champion.icon_url ? (
        <img
          src={champion.icon_url}
          alt=""
          loading="lazy"
          decoding="async"
          className="size-10 shrink-0 ring-1 ring-line"
        />
      ) : (
        <span className="size-10 shrink-0 bg-raised" />
      )}
      <span className="min-w-0 flex-1">
        {/* The games beside the name, so the roles below have the card's
            width: beside them, two roles ran out of room at five columns. */}
        <span className="flex items-baseline gap-2">
          <Link
            to={pathFor(position)}
            viewTransition
            className="display min-w-0 flex-1 truncate text-[15px] font-600 text-ink outline-none after:absolute after:inset-0 hover:text-gold-bright focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            {champion.name}
          </Link>
          {entry.games > 0 && (
            <span className="tnum shrink-0 text-[11px] text-ink-faint">{compact(entry.games)} games</span>
          )}
        </span>
        <span className="tnum block truncate text-xs text-ink-faint">
          {roles.length === 0
            ? patch
              ? `No games on ${patch}`
              : 'No games yet'
            : roles.map((p, i) => (
                <span key={p.position}>
                  {i > 0 && ', '}
                  <Link
                    to={pathFor(p.position)}
                    className="relative z-10 text-ink-dim hover:text-gold-bright"
                  >
                    {positionLabel(p.position)}
                  </Link>{' '}
                  {pct(p.share)}
                </span>
              ))}
        </span>
      </span>
    </li>
  )
}
