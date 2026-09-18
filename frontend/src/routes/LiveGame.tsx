import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import {
  api,
  type CorpusRecord,
  type LiveGame,
  type LiveParticipant,
  type LobbyRank,
  type Position,
} from '../lib/api'
import PositionIcon from '../components/PositionIcon'
import ProfileTabs from '../components/ProfileTabs'
import RankBadge from '../components/RankBadge'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import {
  compact,
  duration,
  pct,
  positionLabel,
  tierColor,
  tierLabel,
  timeAgo,
} from '../lib/format'

const POLL_MS = 60_000
const LANES: Position[] = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']
const BLUE = 100
const RED = 200

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

  // The last game this page saw. When it ends, the next poll says "not in a
  // game", and without this the lineup vanished for a bare empty state, which
  // read as the page losing the game rather than the game finishing. Kept with
  // React's pattern for information from earlier renders, not an effect, so the
  // ended view never flashes the empty one first.
  //
  // Keyed by the player it belongs to. React Router keeps this component alive
  // when the URL moves from one player's live tab to another's, so an unkeyed
  // memory announced player A's finished game on player B's page.
  const player = `${platform}/${name}/${tag}`
  const [seen, setSeen] = useState<{ player: string; game: LiveGame } | null>(null)
  if (data?.in_game && data.game && (!seen || seen.game !== data.game || seen.player !== player)) {
    setSeen({ player, game: data.game })
  }
  const lastGame = seen?.player === player ? seen.game : null
  const ended = Boolean(data && !data.in_game && lastGame)

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
      {ended && lastGame && data && (
        <GameOver game={lastGame} platform={platform} name={name} tag={tag} you={data.puuid} />
      )}
      {!query.isLoading && !(query.isError && !data) && !ended &&
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

function GameOver({
  game,
  platform,
  name,
  tag,
  you,
}: {
  game: LiveGame
  platform: string
  name: string
  tag: string
  you: string
}) {
  return (
    <div className="space-y-5">
      <section
        className="accent-edge bg-panel/50 py-3 pl-4"
        style={{ '--accent': 'var(--color-gold)' } as CSSProperties}
      >
        <h2 className="display text-xl font-700 text-ink">This game has ended</h2>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-ink-dim">
          Riot publishes the result, with gold, items and K/D/A for all ten players, a
          minute or two after the game ends. It appears in the{' '}
          <Link
            to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
            className="text-ink underline decoration-line underline-offset-2 hover:text-gold-bright"
          >
            match history
          </Link>{' '}
          with its full scoreboard. The lineup below is how the game started.
        </p>
      </section>
      <div className="opacity-70">
        <GameView game={game} platform={platform} you={you} stale={false} ended />
      </div>
    </div>
  )
}

function GameView({
  game,
  platform,
  you,
  stale,
  ended = false,
}: {
  game: LiveGame
  platform: string
  you: string
  stale: boolean
  ended?: boolean
}) {
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="display text-2xl font-700 text-ink">{game.queue_name}</h2>
        {ended ? (
          <span className="text-sm text-ink-dim">Ended</span>
        ) : (
          <GameClock game={game} />
        )}
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

      {game.positions_inferred ? (
        <LaneView game={game} platform={platform} you={you} />
      ) : (
        <TeamView game={game} platform={platform} you={you} />
      )}

      <Bans game={game} />
      <Notes game={game} />
    </div>
  )
}

/**
 * Lane by lane, each blue player facing their red opponent.
 *
 * Only when the server could place all ten players: spectator-v5 carries no
 * positions, so they are inferred, and a lobby with some lanes and some blanks
 * has no layout. Everything else falls back to the team columns.
 */
function LaneView({ game, platform, you }: { game: LiveGame; platform: string; you: string }) {
  const at = (team: number, lane: Position) =>
    game.participants.find((p) => p.team_id === team && p.position === lane)
  const confidentAt = game.position_model?.confident_at ?? 0.9

  // Full width, like the rest of the page, with each card pulled in towards the
  // lane icon rather than out to its own edge. Pushed to the edges, the two
  // players in a lane sat a page apart with the icon adrift between them, and
  // nothing on screen said which two were facing each other.
  return (
    <section>
      <div className="mb-1 grid grid-cols-[1fr_3.5rem_1fr] items-end gap-2 border-b border-line pb-1.5 sm:grid-cols-[1fr_6rem_1fr] sm:gap-3">
        <h3
          className="display text-right text-base font-600"
          style={{ color: 'var(--color-win)' }}
        >
          Blue side
        </h3>
        <span />
        <h3 className="display text-base font-600" style={{ color: 'var(--color-loss)' }}>
          Red side
        </h3>
      </div>
      <ul>
        {LANES.map((lane) => {
          const blue = at(BLUE, lane)
          const red = at(RED, lane)
          if (!blue || !red) return null
          return (
            <li
              key={lane}
              className="grid grid-cols-[1fr_3.5rem_1fr] items-center gap-2 border-b border-line-soft py-2 sm:grid-cols-[1fr_6rem_1fr] sm:gap-3"
            >
              <LaneCard
                p={blue}
                side="blue"
                platform={platform}
                isYou={Boolean(blue.puuid) && blue.puuid === you}
              />
              <LaneCenter
                lane={lane}
                blue={blue}
                red={red}
                confidentAt={confidentAt}
                patch={game.corpus_patch}
              />
              <LaneCard
                p={red}
                side="red"
                platform={platform}
                isYou={Boolean(red.puuid) && red.puuid === you}
              />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function LaneCard({
  p,
  side,
  platform,
  isYou,
}: {
  p: LiveParticipant
  side: 'blue' | 'red'
  platform: string
  isYou: boolean
}) {
  const [name, tag] = (p.riot_id ?? '').split('#')
  const linkable = Boolean(p.riot_id && name && tag)
  // Blue is the mirrored side: its art sits on the right, beside the lane icon,
  // so both champions in a lane face each other across it.
  const mirrored = side === 'blue'
  const art = p.skin_tile_url ?? p.champion.icon_url

  return (
    // The cell pushes the card towards the lane icon; the card itself is only
    // as wide as its content, so the "you" outline fits the player, not the
    // whole half of the row.
    <div className={`flex min-w-0 ${mirrored ? 'justify-end' : 'justify-start'}`}>
    <div
      className={`flex min-w-0 max-w-full items-center gap-2.5 rounded-sm px-1.5 py-1 ${
        mirrored ? 'flex-row-reverse text-right' : ''
      } ${isYou ? 'bg-gold/[0.07] ring-1 ring-gold/40' : ''}`}
    >
      {/* The skin this player is wearing, from spectator's own record of it:
          the same art their teammates see on the loading screen. */}
      <span className="size-12 shrink-0 overflow-hidden rounded-sm bg-raised sm:size-14">
        {art && (
          <img src={art} alt={p.champion.name} className="size-full object-cover" loading="lazy" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <p className="display truncate text-[15px] font-600 leading-tight text-ink">
          {p.champion.name}
        </p>
        <p className="truncate text-xs leading-snug">
          {linkable ? (
            <Link
              to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
              className="text-ink-dim transition-colors hover:text-gold-bright"
            >
              {name}
            </Link>
          ) : (
            // Never the champion name Riot puts in `riotId` for a hidden player:
            // it would read as a person and link to a profile that does not exist.
            <span className="text-ink-faint">{p.state === 'bot' ? 'Bot' : 'Hidden player'}</span>
          )}
        </p>
        <div
          className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${
            mirrored ? 'justify-end' : ''
          }`}
        >
          <RankBadge
            state={p.state}
            tier={p.rank?.tier}
            division={p.rank?.division}
            leaguePoints={p.rank?.league_points}
          />
          {p.rank && p.rank.games > 0 && (
            <span
              title={`${p.rank.wins}W ${p.rank.losses}L this season, ${pct(p.rank.win_rate, 1)} win rate`}
              className="tnum whitespace-nowrap text-[11px] text-ink-faint"
            >
              {pct(p.rank.win_rate)} WR
            </span>
          )}
          <MasteryChip p={p} />
        </div>
        <div
          className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${
            mirrored ? 'justify-end' : ''
          }`}
        >
          <Loadout p={p} />
          <RoleRecord p={p} />
        </div>
      </div>
    </div>
    </div>
  )
}

function LaneCenter({
  lane,
  blue,
  red,
  confidentAt,
  patch,
}: {
  lane: Position
  blue: LiveParticipant
  red: LiveParticipant
  confidentAt: number
  patch: string | null
}) {
  // Either side's placement can be the close call, and a lane is only as sure
  // as its less certain half.
  const unsure = [blue, red].some(
    (p) => p.position_basis !== 'smite' && (p.position_confidence ?? 1) < confidentAt,
  )
  // Blue's view of the matchup. The two sides' records are mirror images, so
  // one is shown, and the other is only used if blue's is the one missing.
  const record = blue.lane_record ?? mirror(red.lane_record)

  return (
    <div className="flex flex-col items-center justify-center gap-0.5 text-center">
      <PositionIcon position={lane} className="size-5 text-ink-dim" />
      <span className="display text-xs font-600 text-ink-dim">{positionLabel(lane)}</span>
      {unsure && (
        <span
          className="text-[10px] text-gold"
          title="Riot's live data has no positions, so this lane is inferred from the champions and their summoner spells, and this one is a close call. Measured on held-out games, lanes this uncertain are right about half to two thirds of the time."
        >
          likely
        </span>
      )}
      {record && (
        <span
          className="mt-0.5 w-full"
          title={
            `${blue.champion.name} against ${red.champion.name} as ${positionLabel(lane)}: ` +
            `${record.wins} wins and ${record.games - record.wins} losses in our stored games` +
            (patch ? ` on patch ${patch}` : '') +
            '. This is the matchup, not these two players.' +
            (record.gold_diff_14 != null
              ? ` ${blue.champion.name} averages ${signed(Math.round(record.gold_diff_14))} gold at 14 minutes, over ${record.timeline_games} games with timelines.`
              : '')
          }
        >
          {/* Blue's share of the matchup's wins, as blue against red. */}
          <span className="flex h-1 w-full overflow-hidden rounded-full bg-loss/70">
            <span
              className="h-full bg-win"
              style={{ width: `${Math.round(record.win_rate * 100)}%` }}
            />
          </span>
          <span className="tnum mt-0.5 block text-[11px] text-ink-dim">
            {record.wins}-{record.games - record.wins}
          </span>
          {record.gold_diff_14 != null && (
            <span
              className="tnum block text-[10px]"
              style={{
                color:
                  record.gold_diff_14 >= 0 ? 'var(--color-win)' : 'var(--color-loss)',
              }}
            >
              {signed(Math.round(record.gold_diff_14))}g
            </span>
          )}
        </span>
      )}
    </div>
  )
}

function MasteryChip({ p }: { p: LiveParticipant }) {
  // Not known: the lookup did not finish, which says nothing about the player.
  if (!p.mastery_known) return null
  if (!p.mastery) {
    return (
      <span
        className="text-[11px] text-ink-faint"
        title={`Riot reports no mastery on ${p.champion.name} for this player, so this may be their first game on it.`}
      >
        No mastery
      </span>
    )
  }
  const m = p.mastery
  return (
    <span
      className="tnum whitespace-nowrap text-[11px] text-ink-dim"
      title={
        `Mastery ${m.level} on ${p.champion.name}, ${m.points.toLocaleString()} points` +
        (m.last_play_time ? `. Last played ${timeAgo(m.last_play_time)}.` : '.')
      }
    >
      <span className="font-600 text-gold-bright">M{m.level}</span> {compact(m.points)}
    </span>
  )
}

function RoleRecord({ p }: { p: LiveParticipant }) {
  const r = p.champion_record
  if (!r) return null
  return (
    // "Champ WR", not "Pick": on the tier list "Pick" is the pick rate, and one
    // word meaning two numbers on one site is how people misread both.
    <span
      className="tnum whitespace-nowrap text-[11px] text-ink-faint"
      title={`${p.champion.name} as ${positionLabel(p.position)} in our stored games: ${r.wins} wins, ${r.games - r.wins} losses, ${pct(r.win_rate, 1)}. This is the champion, not this player.`}
    >
      Champ WR {pct(r.win_rate)}
    </span>
  )
}

function Loadout({ p }: { p: LiveParticipant }) {
  return (
    <span className="flex items-center gap-0.5">
      {p.spells.map((s, i) => (
        <img
          key={`${s.id}-${i}`}
          src={s.icon_url ?? undefined}
          alt={s.name ?? ''}
          title={s.name ?? ''}
          className="size-4 rounded-sm bg-raised"
          loading="lazy"
        />
      ))}
      {p.keystone?.icon_url && (
        <span className="ml-0.5 grid size-4 place-items-center rounded-full bg-raised">
          <img src={p.keystone.icon_url} alt="" className="size-3.5" loading="lazy" />
        </span>
      )}
      {p.secondary_tree?.icon_url && (
        <img src={p.secondary_tree.icon_url} alt="" className="size-3" loading="lazy" />
      )}
    </span>
  )
}

function TeamView({ game, platform, you }: { game: LiveGame; platform: string; you: string }) {
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
  )
}

function Bans({ game }: { game: LiveGame }) {
  if (game.bans.length === 0) return null
  const sided = game.positions_inferred
  const groups = sided
    ? [
        { key: BLUE, label: 'Blue bans', color: 'var(--color-win)', bans: game.bans.filter((b) => b.team_id === BLUE) },
        { key: RED, label: 'Red bans', color: 'var(--color-loss)', bans: game.bans.filter((b) => b.team_id === RED) },
      ]
    : [{ key: 0, label: 'Bans', color: 'var(--color-ink)', bans: game.bans }]

  // Beside the lanes they belong to: blue's pulled in towards the middle from
  // the left and red's from the right, the same way the lane cards are.
  return (
    <section
      className={`grid gap-3 ${sided ? 'grid-cols-2 gap-x-[4.5rem] sm:gap-x-[7.5rem]' : ''}`}
    >
      {groups.map((g, i) => (
        <div key={g.key} className={sided && i === 0 ? 'text-right' : ''}>
          <h3 className="mb-2 display text-sm font-600" style={{ color: g.color }}>
            {g.label}
          </h3>
          <div className={`flex flex-wrap gap-1 ${sided && i === 0 ? 'justify-end' : ''}`}>
            {g.bans.map((b, j) => (
              <span
                key={`${b.champion.id}-${j}`}
                className="size-7 overflow-hidden rounded-sm bg-raised grayscale"
                title={b.champion.name}
              >
                {b.champion.icon_url && (
                  <img src={b.champion.icon_url} alt={b.champion.name} loading="lazy" />
                )}
              </span>
            ))}
            {g.bans.length === 0 && <span className="text-xs text-ink-faint">None</span>}
          </div>
        </div>
      ))}
    </section>
  )
}

function Notes({ game }: { game: LiveGame }) {
  const model = game.position_model
  return (
    <div className="max-w-prose space-y-1.5 text-xs leading-relaxed text-ink-faint">
      {model && (
        <p>
          Riot&apos;s live data has no positions, so each lane is inferred from the
          champions and their summoner spells, and a team&apos;s only Smite is always
          the jungler. Tested on {model.players_tested.toLocaleString()} players from
          our stored games that the model had not seen, it placed{' '}
          {pct(model.accuracy, 1)} of them correctly. A lane marked
          &ldquo;likely&rdquo; is one of the closer calls.
        </p>
      )}
      {game.corpus_patch && (
        <p>
          &ldquo;Champ WR&rdquo; and the lane records between opponents come from our
          stored games on patch {game.corpus_patch}, and appear only where there are
          enough of them. They describe the champions, not these players.
        </p>
      )}
      <p>
        Riot does not publish gold, items or K/D/A for a game in progress, to anyone.
        They arrive with the result, in the match history, once the game ends.
      </p>
      <p>
        Since 2025 players can hide their identity from third-party tools. Around a
        third of a typical lobby does, so anyone marked Hidden has no name, rank or
        mastery here, and the median above is taken over a sample rather than a
        census.
      </p>
    </div>
  )
}

function mirror(r: CorpusRecord | null): CorpusRecord | null {
  if (!r) return null
  return {
    ...r,
    wins: r.games - r.wins,
    win_rate: 1 - r.win_rate,
    gold_diff_14: r.gold_diff_14 == null ? null : -r.gold_diff_14,
  }
}

function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`
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
        {(p.skin_tile_url ?? p.champion.icon_url) && (
          <img
            src={p.skin_tile_url ?? p.champion.icon_url ?? undefined}
            alt={p.champion.name}
            className="size-full object-cover"
            loading="lazy"
          />
        )}
      </span>

      <Loadout p={p} />

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

      <MasteryChip p={p} />
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
