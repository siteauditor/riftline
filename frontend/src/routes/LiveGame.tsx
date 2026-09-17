import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api, type LiveGame, type LiveParticipant, type LobbyRank } from '../lib/api'
import ProfileTabs from '../components/ProfileTabs'
import RankBadge from '../components/RankBadge'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { duration, pct, tierColor, tierLabel } from '../lib/format'

const POLL_MS = 60_000

export default function LiveGamePage() {
  const { platform = '', name = '', tag = '' } = useParams()

  const query = useQuery({
    queryKey: ['live', platform, name, tag],
    queryFn: () => api.live(platform, name, tag),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
  })

  const data = query.data

  // One shell around every branch, matching the other routes: without it the
  // page sits flush against the viewport edge while the header stays centred.
  return (
    <div className="mx-auto max-w-[1280px] px-4 py-6">
      {/* The same header the other two tabs carry. Without it this page was a
          strip of tabs and an empty box, with nothing saying whose it was. */}
      <header className="mb-5 flex flex-wrap items-center gap-4 border-b border-line-soft pb-5">
        <div>
          <h1 className="display text-[clamp(1.9rem,4vw,2.6rem)] font-700 text-ink">
            {name}
            <span className="ml-1.5 text-lg font-600 text-ink-faint">#{tag}</span>
          </h1>
          <p className="mt-0.5 text-sm text-ink-dim">Live game</p>
        </div>
        <ProfileTabs platform={platform} name={name} tag={tag} />
      </header>

      {query.isLoading && <Spinner label="Checking for a live game" />}
      {/* Only when there is nothing to show. A refetch failure keeps `data`, so
          an unguarded error branch stacked "Riot isn't responding" on top of a
          full lobby whose clock was still counting up. A blip on the 60-second
          poll should be invisible; losing the data entirely should not. */}
      {query.isError && !data && (
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      )}
      {!query.isLoading && !(query.isError && !data) &&
        (!data?.in_game || !data.game) && (
          <EmptyState
            title="Not in a game right now"
            body="This page checks again every minute while it is open."
          />
        )}
      {data?.in_game && data.game && (
        <GameView
          game={data.game}
          platform={platform}
          you={data.puuid}
          stale={query.isError}
        />
      )}
    </div>
  )
}

function GameView({
  game,
  platform,
  you,
  stale,
}: {
  game: LiveGame
  platform: string
  you: string
  stale: boolean
}) {
  // Grouped by whatever team ids the mode actually uses, not a hardcoded
  // 100/200. Arena runs eight teams of two, and assuming two sides renders two
  // empty columns and dumps all sixteen players into a third. MatchRow already
  // learned this lesson; this is the same rule.
  const byTeam = new Map<number, LiveParticipant[]>()
  for (const p of game.participants) {
    const bucket = byTeam.get(p.team_id)
    if (bucket) bucket.push(p)
    else byTeam.set(p.team_id, [p])
  }
  const teams = [...byTeam.entries()].sort(([a], [b]) => a - b)
  const twoSided = teams.length === 2
  // Arena reports all sixteen or eighteen players under one team id: its real
  // pairs live in a field spectator-v5 does not carry. One group is therefore
  // one group, and calling it "Team 1" would invent a division we cannot see.
  const oneGroup = teams.length === 1

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="display text-2xl font-700 text-ink">{game.queue_name}</h2>
        <GameClock game={game} />
        {!game.you_identified && (
          <span className="text-xs text-ink-faint">
            This player hides their identity, so their own row is not marked
          </span>
        )}
        {stale && (
          <span className="text-xs text-loss">
            Could not refresh; showing the last successful check
          </span>
        )}
      </header>

      {game.lobby_rank && <LobbyRankCard lobby={game.lobby_rank} />}

      <div className={`grid gap-4 ${oneGroup ? '' : 'lg:grid-cols-2'}`}>
        {teams.map(([teamId, team], i) => (
          <section key={teamId}>
            <h3
              className="mb-1 border-b border-line pb-1.5 display text-base font-600"
              style={{
                color: twoSided
                  ? i === 0
                    ? 'var(--color-win)'
                    : 'var(--color-loss)'
                  : 'var(--color-ink)',
              }}
            >
              {twoSided
                ? i === 0
                  ? 'Blue side'
                  : 'Red side'
                : oneGroup
                  ? `All ${team.length} players`
                  : `Team ${i + 1}`}
            </h3>
            <ul className={oneGroup ? 'sm:grid sm:grid-cols-2 sm:gap-x-4' : ''}>
              {team.map((p, j) => (
                <PlayerRow
                  key={p.puuid ?? `${teamId}-${j}`}
                  p={p}
                  platform={platform}
                  isYou={Boolean(p.puuid) && p.puuid === you}
                />
              ))}
            </ul>
          </section>
        ))}
      </div>

      {game.banned_champions.length > 0 && (
        <section>
          <h3 className="mb-2 display text-base font-600 text-ink">Bans</h3>
          <div className="flex flex-wrap gap-1">
            {game.banned_champions.map((c, i) => (
              <span
                key={`${c.id}-${i}`}
                className="size-7 overflow-hidden rounded-sm bg-raised grayscale"
                title={c.name}
              >
                {c.icon_url && <img src={c.icon_url} alt={c.name} loading="lazy" />}
              </span>
            ))}
          </div>
        </section>
      )}

      <p className="text-xs leading-relaxed text-ink-faint">
        Since 2025 players can hide their identity from third-party tools. Around a
        third of a typical lobby does, so anyone marked Hidden has no name and no
        rank here, and the median above is taken over a sample rather than a
        census.
      </p>
    </div>
  )
}

/**
 * The clock runs locally from `observed_at`, rather than polling the server for
 * a number it can work out itself.
 */
function GameClock({ game }: { game: LiveGame }) {
  // Counted from when *this browser* received the payload, not differenced
  // against the server's wall clock. `Date.now() - observed_at` measures the
  // skew between the two machines, which is routinely tens of seconds: a
  // browser running behind pinned the delta at zero and the timer sat frozen
  // between polls, and one running ahead read permanently too high.
  const [elapsed, setElapsed] = useState(game.game_length)

  useEffect(() => {
    const receivedAt = Date.now()
    const base = game.game_length
    const id = setInterval(
      () => setElapsed(base + (Date.now() - receivedAt) / 1000),
      1000,
    )
    return () => clearInterval(id)
  }, [game.observed_at, game.game_length])

  if (game.phase === 'loading') {
    return <span className="text-sm text-ink-dim">Champion select or loading</span>
  }
  return (
    <span className="tnum text-sm text-ink-dim">
      {duration(Math.max(0, Math.floor(elapsed)))}
    </span>
  )
}

function LobbyRankCard({ lobby }: { lobby: LobbyRank }) {
  const counted = [
    lobby.hidden > 0 && `${lobby.hidden} hid their identity`,
    lobby.unranked > 0 && `${lobby.unranked} unranked`,
    lobby.unknown > 0 && `${lobby.unknown} could not be looked up`,
    lobby.bots > 0 && `${lobby.bots} bots`,
  ].filter(Boolean) as string[]

  if (lobby.median_points === null) {
    return (
      <section className="accent-edge bg-panel/50 py-2.5 pl-4">
        <h3 className="display text-lg font-600 text-ink">
          Not enough identified players
        </h3>
        <p className="mt-1 text-xs text-ink-faint">
          Only {lobby.ranked} {lobby.ranked === 1 ? 'player' : 'players'} in this
          lobby {lobby.ranked === 1 ? 'exposes' : 'expose'} a rank
          {counted.length > 0 && `. ${counted.join(', ')}`}.
        </p>
      </section>
    )
  }

  const accent = tierColor(lobby.tier)
  return (
    // A band in the lobby's own colour rather than a card: this is the headline
    // measurement of the page, and the tier colour is how it is read first.
    <section
      className="accent-edge bg-panel/50 py-2.5 pl-4"
      style={{ '--accent': accent } as CSSProperties}
    >
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-sm text-ink-dim">Median rank</h3>
        <p className="display text-2xl font-700" style={{ color: accent }}>
          {tierLabel(lobby.tier, lobby.division)}
          {lobby.league_points != null && (
            <span className="tnum ml-2 text-base font-600 text-ink-dim">
              {lobby.league_points.toLocaleString()} LP
            </span>
          )}
        </p>
      </div>
      <p className="mt-1.5 text-xs text-ink-faint">
        Median of {lobby.ranked} identified{' '}
        {lobby.ranked === 1 ? 'player' : 'players'}
        {counted.length > 0 && `. ${counted.join(', ')}`}.
        {!lobby.queue_matches_game &&
          ' Solo queue rank is shown, because this queue has no rank of its own.'}
      </p>
    </section>
  )
}

function PlayerRow({
  p,
  platform,
  isYou,
}: {
  p: LiveParticipant
  platform: string
  isYou: boolean
}) {
  const [name, tag] = (p.riot_id ?? '').split('#')
  const linkable = Boolean(p.riot_id && name && tag)

  return (
    <li
      className={`flex items-center gap-2.5 border-b border-l-2 border-line-soft px-2 py-2 transition-colors hover:bg-raised/30 ${
        isYou ? 'border-l-gold bg-gold/[0.06]' : 'border-l-transparent'
      }`}
    >
      <span className="size-9 shrink-0 overflow-hidden rounded-sm bg-raised">
        {p.champion.icon_url && (
          <img src={p.champion.icon_url} alt={p.champion.name} loading="lazy" />
        )}
      </span>

      <span className="flex shrink-0 flex-col gap-0.5">
        {p.spells.map((s, i) => (
          <img
            key={`${s.id}-${i}`}
            src={s.icon_url ?? undefined}
            alt={s.name ?? ''}
            title={s.name ?? ''}
            className="size-[15px] rounded-sm bg-raised"
            loading="lazy"
          />
        ))}
      </span>

      <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-raised">
        {p.keystone?.icon_url && (
          <img src={p.keystone.icon_url} alt="" className="size-4" loading="lazy" />
        )}
      </span>

      <span className="min-w-0 flex-1 truncate text-sm">
        {linkable ? (
          <Link
            to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
            className="display text-[15px] font-600 text-ink transition-colors hover:text-gold-bright"
          >
            {name}
          </Link>
        ) : (
          // Never the champion name Riot puts in `riotId` for a hidden player:
          // it would read as a person and link to a profile that does not exist.
          <span className="display text-[15px] font-600 text-ink-faint">
            {p.champion.name}
          </span>
        )}
      </span>

      <RankBadge
        state={p.state}
        tier={p.rank?.tier}
        division={p.rank?.division}
        leaguePoints={p.rank?.league_points}
      />
      {p.rank && p.rank.games > 0 && (
        <span
          title={`${p.rank.wins}W ${p.rank.losses}L this season, ${pct(p.rank.win_rate, 1)} win rate`}
          className="tnum hidden w-16 shrink-0 text-right text-xs text-ink-faint sm:block"
        >
          {pct(p.rank.win_rate)} WR
        </span>
      )}
    </li>
  )
}
