import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import MostWornSkins from '../components/MostWornSkins'
import PositionIcon from '../components/PositionIcon'
import SearchBar from '../components/SearchBar'
import { SectionTitle } from '../components/Stat'
import {
  POSITIONS,
  type BestGame,
  type ChampionMetaRow,
  type CorpusResponse,
} from '../lib/api'
import {
  compact,
  pct,
  positionLabel,
  scoreColor,
  winRateColor,
} from '../lib/format'
import { clearRecentSearches, useRecentSearches } from '../lib/storage'
import { queries } from '../lib/queries'
import { heads } from '../lib/seo'
import TimeAgo from '../components/TimeAgo'

// Two accounts with a real history behind them. The previous EUW example was
// `Caps#EUW`, which resolves to an unranked level 31 with no games: the first
// thing a new visitor clicked landed them on an empty profile.
const EXAMPLES = [
  { platform: 'kr', name: 'Hide on bush', tag: 'KR1', label: 'Hide on bush#KR1' },
  { platform: 'euw1', name: 'J1HUIV', tag: '000', label: 'J1HUIV#000' },
]

const SOLO_QUEUE = 420

function profilePath(platform: string, name: string, tag: string) {
  return `/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`
}

/**
 * Landing view.
 *
 * The search is the product, so it stays the first thing, and it now remembers:
 * the region, and the profiles this browser opened. Below it, everything is
 * read from what is already stored, so the page costs no Riot calls at all: the
 * three things only Riftline does, the strongest pick in each role, and the
 * best-scored game in each role this week.
 */
export default function Home() {
  const meta = useQuery({
    ...queries.meta({ minGames: 40 }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
  const corpus = useQuery({
    ...queries.corpus(),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })
  const best = useQuery({
    ...queries.bestGames(),
    staleTime: 10 * 60 * 1000,
    retry: false,
  })

  // The hero's art is the strongest pick on the patch: the page's own subject,
  // not a stock background.
  const champions = useQuery({
    ...queries.champions(),
    staleTime: 6 * 60 * 60 * 1000,
  })
  const leadChampion = meta.data?.rows[0]?.champion.id
  const heroArt =
    champions.data?.champions.find((c) => c.id === leadChampion)?.art_url ?? null

  return (
    <div>
      <Head {...heads.home()} />
      <ArtHeader art={heroArt} tall>
        <div className="pb-2 pt-6 sm:pt-10">
          {/* Broken by hand. Left to a measure, the rag landed on "read at /
              a glance", which splits the phrase that carries the meaning. */}
          <h1 className="display text-[clamp(2.7rem,7vw,5rem)] font-800 uppercase leading-[0.92] tracking-[-0.01em] text-ink">
            Every game you
            <br />
            have played
          </h1>
          <p className="mt-3 max-w-[46ch] text-[15px] leading-relaxed text-ink-dim">
            Rank, match history, champion mastery and the meta, for any League of
            Legends player, with a score on every game. Search a Riot ID to start.
          </p>

          <div className="mt-8 max-w-xl">
            <SearchBar size="large" autoFocus />
          </div>

          <RecentOrExamples />

          {corpus.data && <CorpusLine corpus={corpus.data} />}
        </div>
      </ArtHeader>

      <WhatsHere hasBestGames={(best.data?.games.length ?? 0) > 0} />

      <BestPicks meta={meta} />

      <BestGames best={best} />

      <MostWornSkins />
    </div>
  )
}

/** Profiles this browser opened, or two examples for a first visit. */
function RecentOrExamples() {
  const recent = useRecentSearches()

  if (recent.length === 0) {
    return (
      <div className="mt-4 flex max-w-xl flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-faint">Try</span>
        {EXAMPLES.map((e) => (
          <Link
            key={e.label}
            to={profilePath(e.platform, e.name, e.tag)}
            className="border-b border-line text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
          >
            {e.label}
          </Link>
        ))}
      </div>
    )
  }

  return (
    <div className="mt-4 flex max-w-xl flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <span className="text-ink-faint">Recent</span>
      {recent.map((r) => (
        <Link
          key={`${r.platform}:${r.gameName}#${r.tagLine}`}
          to={profilePath(r.platform, r.gameName, r.tagLine)}
          className="group inline-flex min-w-0 max-w-full items-center gap-1.5 text-ink-dim"
        >
          {r.iconUrl ? (
            <img src={r.iconUrl} alt="" className="size-5 shrink-0 rounded-sm" />
          ) : (
            <span aria-hidden className="size-5 shrink-0 rounded-sm bg-raised" />
          )}
          <span className="truncate border-b border-line transition-colors group-hover:border-gold group-hover:text-gold-bright">
            {r.gameName}
            <span className="text-ink-faint">#{r.tagLine}</span>
          </span>
        </Link>
      ))}
      <button
        type="button"
        onClick={clearRecentSearches}
        className="text-xs text-ink-faint transition-colors hover:text-ink"
      >
        Clear
      </button>
    </div>
  )
}

/**
 * Where the numbers come from, and how old the newest of them is.
 *
 * The age is stated rather than a schedule: with an expired development key the
 * nightly crawl is skipped, and "updated nightly" would then claim a freshness
 * the data does not have.
 */
function CorpusLine({ corpus }: { corpus: CorpusResponse }) {
  // Newest patch first, as the server sends them. Not a patch range: a handful
  // of stray games from old patches (16.8, 16.9) would stretch "16.8 to 16.18"
  // over a gap the data does not cover. The newest patch is what the tier list
  // reads, so that is the share worth stating.
  const solo = corpus.slices.filter((s) => s.queue_id === SOLO_QUEUE)
  if (solo.length === 0) return null
  const games = solo.reduce((sum, s) => sum + s.matches, 0)
  const newest = solo[0]

  return (
    <p className="mt-6 max-w-xl text-xs leading-relaxed text-ink-faint">
      Built from <span className="tnum text-ink-dim">{games.toLocaleString('en-US')}</span> ranked
      solo games
      {solo.length > 1 && (
        <>
          , <span className="tnum text-ink-dim">{newest.matches.toLocaleString('en-US')}</span> of them
        </>
      )}{' '}
      on patch {newest.patch}.
      {corpus.latest_game_at !== null && (
        <> The newest was played <TimeAgo at={corpus.latest_game_at} />.</>
      )}
    </p>
  )
}

/** The three things Riftline does that a rank lookup does not. */
function WhatsHere({ hasBestGames }: { hasBestGames: boolean }) {
  const items = [
    {
      title: 'Riftline score',
      body:
        'Ranked games scored from 0 to 10 against players in the same role, with ' +
        'the weights published so the number can be checked.',
      link: hasBestGames ? { to: '#best-games', label: "See this week's best games" } : null,
    },
    {
      title: 'Live games, lane by lane',
      body:
        "When a player is in game, their Live tab lines up each lane: both players, " +
        'their mastery on the pick, and how that matchup usually goes.',
      link: { to: '/leaderboards', label: 'Find a top player on the leaderboards' },
    },
    {
      title: 'A tier list that counts games',
      body:
        'Champions ranked by the win rate their sample can support, so a pick ' +
        'that went 3-0 does not top the list.',
      link: { to: '/tierlist', label: 'Open the tier list' },
    },
  ]

  return (
    <section aria-label="What Riftline shows" className="border-b border-line-soft bg-panel/40">
      <ul className="mx-auto grid max-w-[1280px] gap-x-10 gap-y-7 px-4 py-9 md:grid-cols-3">
        {items.map((item) => (
          <li key={item.title} className="accent-edge pl-4">
            <h2 className="display text-xl font-600 text-ink">{item.title}</h2>
            <p className="mt-1.5 max-w-[46ch] text-sm leading-relaxed text-ink-dim">
              {item.body}
            </p>
            {item.link &&
              (item.link.to.startsWith('#') ? (
                <a
                  href={item.link.to}
                  className="mt-2 inline-block border-b border-line text-sm text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
                >
                  {item.link.label}
                </a>
              ) : (
                <Link
                  to={item.link.to}
                  className="mt-2 inline-block border-b border-line text-sm text-ink-dim transition-colors hover:border-gold hover:text-gold-bright"
                >
                  {item.link.label}
                </Link>
              ))}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * The strongest champion in each role.
 *
 * One per role rather than the six strongest overall, which can skip a role
 * entirely: on the local corpus on 2026-09-19 the six strongest on patch 16.18
 * held two top laners, two supports and no bot laner at all.
 */
function BestPicks({
  meta,
}: {
  meta: { data?: { patch: string; rows: ChampionMetaRow[] }; isLoading: boolean }
}) {
  const rows = meta.data?.rows ?? []
  // The server sends every role sorted by the adjusted win rate, so the first
  // row seen for a role is its best. A role with no champion over the floor is
  // left out rather than filled with a thin one.
  const picks = POSITIONS.map((p) => rows.find((r) => r.position === p.id)).filter(
    (r): r is ChampionMetaRow => r !== undefined,
  )

  if (!meta.isLoading && picks.length === 0) return null

  return (
    <section className="mx-auto max-w-[1280px] px-4 pt-10">
      <SectionTitle
        eyebrow="Patch meta"
        title="Best pick in each role"
        aside={
          <Link to="/tierlist" className="transition-colors hover:text-accent-bright">
            See the full tier list
          </Link>
        }
      />
      <p className="mt-1 max-w-[62ch] text-sm text-ink-dim">
        The highest win rate each role's sample actually supports, over 40 games or
        more{meta.data ? `, on patch ${meta.data.patch}` : ''}. A champion at 3-0 is
        not the strongest in the game.
      </p>

      {meta.isLoading ? (
        <ul
          aria-hidden
          className="skeleton-breathing mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5"
        >
          {POSITIONS.map((p) => (
            <li key={p.id} className="skeleton aspect-[3/4]" />
          ))}
        </ul>
      ) : (
        <ul className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
          {picks.map((row) => (
            <li key={row.position}>
              <Link
                to={`/champions/${row.champion.slug ?? row.champion.id}?position=${row.position}`}
                className="group block overflow-hidden rounded-sm ring-1 ring-line transition-[box-shadow] hover:ring-gold"
              >
                {/* Tile art, not a 48px icon. The art is the point. */}
                <span className="relative block aspect-[3/4] overflow-hidden bg-raised">
                  {row.champion.tile_url && (
                    <img
                      src={row.champion.tile_url}
                      alt=""
                      loading="lazy"
                      className="size-full object-cover object-top"
                    />
                  )}
                  <span
                    aria-hidden
                    className="absolute inset-0"
                    style={{
                      backgroundImage:
                        'linear-gradient(to top, var(--color-deep) 6%, color-mix(in srgb, var(--color-deep) 45%, transparent) 46%, transparent 78%)',
                    }}
                  />
                  <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-sm bg-deep/80 px-1.5 py-0.5 text-xs font-600 text-ink">
                    <PositionIcon position={row.position} className="size-3.5" />
                    {positionLabel(row.position)}
                  </span>
                  <span className="absolute inset-x-0 bottom-0 p-2.5">
                    <span className="display block truncate text-[15px] font-600 text-ink">
                      {row.champion.name}
                    </span>
                    <span className="mt-0.5 flex items-baseline gap-1.5">
                      <span
                        className="tnum display text-lg font-700"
                        style={{ color: winRateColor(row.confidence_win_rate, 0.52) }}
                      >
                        {pct(row.confidence_win_rate, 1)}
                      </span>
                      <span className="tnum text-[11px] text-ink-faint">
                        {compact(row.games)} games
                      </span>
                    </span>
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/**
 * The best-scored game in each role over the last week.
 *
 * Per role for the same reason as the picks above: on 2026-09-19 the eight
 * highest scores of the week were all top, mid and bot laners, and a support
 * near the top is the best evidence that the score is not a kill count.
 */
function BestGames({
  best,
}: {
  best: {
    data?: { games: BestGame[]; days: number; scored_players: number }
    isLoading: boolean
  }
}) {
  if (!best.isLoading && !best.data?.games.length) return null

  return (
    <section id="best-games" className="mx-auto max-w-[1280px] scroll-mt-20 px-4 py-10">
      <SectionTitle eyebrow="Seven days" title="Best games this week" />
      <p className="mt-1 max-w-[62ch] text-sm text-ink-dim">
        The highest Riftline score in each role over the last{' '}
        {best.data?.days ?? 7} days of ranked solo
        {best.data ? (
          <>
            , out of{' '}
            <span className="tnum">{best.data.scored_players.toLocaleString('en-US')}</span>{' '}
            scored players
          </>
        ) : null}
        . Open a game to see how its score was built.
      </p>

      {best.isLoading ? (
        <ul aria-hidden className="skeleton-breathing mt-4 max-w-3xl">
          {POSITIONS.map((p) => (
            <li
              key={p.id}
              className="flex items-center gap-3 border-b border-line-soft py-3 sm:gap-4"
            >
              <span className="skeleton size-5 sm:w-20" />
              <span className="skeleton size-12" />
              <span className="flex-1 space-y-1.5">
                <span className="skeleton block h-4 w-40 max-w-full" />
                <span className="skeleton block h-3 w-28" />
              </span>
              <span className="skeleton h-8 w-12" />
            </li>
          ))}
        </ul>
      ) : (
        <ul className="mt-4 max-w-3xl">
          {best.data!.games.map((game) => (
            <BestGameRow key={game.match_id + game.puuid} game={game} />
          ))}
        </ul>
      )}
    </section>
  )
}

function BestGameRow({ game }: { game: BestGame }) {
  const badge = game.badges[0]
  const named = game.game_name && game.tag_line
  return (
    <li className="grid grid-cols-[auto_auto_1fr_auto] items-center gap-x-3 border-b border-line-soft py-3 sm:grid-cols-[88px_auto_1fr_auto_auto] sm:gap-x-4">
      <span className="flex items-center gap-1.5 text-sm text-ink-dim">
        <PositionIcon position={game.position} className="size-5 shrink-0" />
        <span className="hidden sm:inline">{positionLabel(game.position)}</span>
        <span className="sr-only sm:hidden">{positionLabel(game.position)}</span>
      </span>

      {game.champion.tile_url ? (
        <img
          src={game.champion.tile_url}
          alt=""
          loading="lazy"
          className="size-12 rounded-sm object-cover object-top"
        />
      ) : (
        <span aria-hidden className="size-12 rounded-sm bg-raised" />
      )}

      <div className="min-w-0">
        {named ? (
          <Link
            to={profilePath(game.platform, game.game_name!, game.tag_line!)}
            className="display block truncate text-lg font-600 text-ink transition-colors hover:text-gold-bright"
          >
            {game.game_name}
            <span className="text-ink-faint">#{game.tag_line}</span>
          </Link>
        ) : (
          <span className="display block text-lg font-600 text-ink-dim">Unnamed player</span>
        )}
        <p className="flex flex-wrap items-baseline gap-x-2.5 text-sm text-ink-dim">
          <span>{game.champion.name}</span>
          <span className="tnum text-ink">
            {game.kills}/{game.deaths}/{game.assists}
          </span>
          <span className={game.win ? 'text-win' : 'text-loss'}>
            {game.win ? 'Win' : 'Loss'}
          </span>
          <TimeAgo at={game.game_creation} className="text-ink-faint" />
        </p>
      </div>

      <span className="hidden sm:block">
        {badge && (
          <span
            title={badge.detail}
            className="rounded-sm bg-gold/15 px-1.5 py-0.5 text-[11px] font-600 text-gold-bright"
          >
            {badge.label}
          </span>
        )}
      </span>

      <div className="text-right">
        <span
          className="tnum display block text-3xl font-700 leading-none"
          style={{ color: scoreColor(game.score) }}
          title={`Riftline score ${game.score.toFixed(2)} of 10`}
        >
          {game.score.toFixed(1)}
        </span>
        <Link
          to={`/match/${game.match_id}?player=${encodeURIComponent(game.puuid)}`}
          className="mt-1 inline-block whitespace-nowrap text-xs text-ink-dim underline decoration-line underline-offset-2 transition-colors hover:text-gold-bright hover:decoration-gold"
        >
          Open the game
        </Link>
      </div>
    </li>
  )
}
