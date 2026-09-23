import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { api, type LiveGame } from '../lib/api'
import { queries } from '../lib/queries'
import { heads } from '../lib/seo'
import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import GameView from '../components/live/GameView'
import IdleView from '../components/live/IdleView'
import PollClock from '../components/live/PollClock'
import StatusBand from '../components/live/StatusBand'
import ProfileTabs from '../components/ProfileTabs'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { duration, ordinal, scoreColor } from '../lib/format'
import { useChampionArt } from '../lib/useChampionArt'
import { useMatchHistory } from '../lib/useMatchHistory'

const POLL_MS = 60_000
// Champion select lasts a couple of minutes and then the lobby becomes a game,
// so the page checks twice as often while it is in that window.
const SELECT_POLL_MS = 30_000
// Three asks for the result of a finished game, a minute apart. The server caps
// the spend at the same number per match id, so extra tabs cost nothing.
const RESULT_ATTEMPTS = 3

export default function LiveGamePage() {
  const { platform = '', name = '', tag = '' } = useParams()

  const query = useQuery({
    queryKey: ['live', platform, name, tag],
    queryFn: () => api.live(platform, name, tag),
    refetchInterval: (query) =>
      query.state.data?.game?.phase === 'loading' ? SELECT_POLL_MS : POLL_MS,
    refetchIntervalInBackground: false,
    staleTime: 30_000,
  })

  const data = query.data

  // The profile is nearly always already cached: this tab is reached from it.
  // The same definition as the profile page's, so the two share one entry.
  const profileQuery = useQuery({
    ...queries.profile(platform, name, tag),
    enabled: Boolean(platform && name && tag),
  })
  // History costs Riot calls, so it is read only on the branch that shows it:
  // a lobby in progress keeps this page down to one spectator lookup.
  const { query: historyQuery, matches } = useMatchHistory(platform, name, tag, {
    enabled: Boolean(data) && !data?.in_game,
  })

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
  // The champion the searched player is on, in the live game or in the one
  // that just ended: this page is about them, so the art is theirs.
  const shown = data?.game ?? lastGame
  // The champion they are on, then the one they just finished on, then the one
  // in the newest game we hold. A page with no art at all read as the art
  // having failed to load, and this page is idle almost every time it is open.
  const heroArt = useChampionArt(
    shown?.participants.find((p) => p.puuid && p.puuid === data?.puuid)?.champion.id ??
      matches.find((m) => !m.is_remake)?.champion.id ??
      data?.idle?.last_game?.champion.id,
  )
  const poll = (
    <PollClock
      updatedAt={query.dataUpdatedAt}
      intervalMs={data?.game?.phase === 'loading' ? SELECT_POLL_MS : POLL_MS}
      fetching={query.isFetching}
      onCheck={() => query.refetch()}
    />
  )

  // One shell around every branch, matching the other routes: without it the
  // page sits flush against the viewport edge while the header stays centred.
  return (
    <div>
      {/* The same header the other two tabs carry. Without it this page was a
          strip of tabs and an empty box, with nothing saying whose it was. */}
      <Head {...heads.profileTab(`${name}#${tag}`, platform, 'live')} />
      <ArtHeader art={heroArt}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-0">
            <p className="eyebrow">Live game</p>
            <h1 className="display mt-1 text-[clamp(1.9rem,4.5vw,2.9rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
              {name}
              <span className="ml-2 text-[0.5em] font-600 text-ink-faint">#{tag}</span>
            </h1>
            <p className="mt-2 flex items-center gap-2 text-sm">
              {data?.in_game ? (
                <>
                  <span className="size-2 animate-pulse rounded-full bg-accent-bright" />
                  <span className="text-accent-bright">Live now</span>
                </>
              ) : ended ? (
                <span className="text-gold-bright">Game ended</span>
              ) : (
                <span className="text-ink-dim">Not in a game</span>
              )}
            </p>
          </div>
          <ProfileTabs platform={platform} name={name} tag={tag} />
        </div>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">

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
        (!data?.in_game || !data.game) &&
        (data?.idle ? (
          <IdleView
            idle={data.idle}
            profile={profileQuery.data}
            matches={matches}
            loading={historyQuery.isLoading}
            platform={platform}
            name={name}
            tag={tag}
            poll={poll}
          />
        ) : (
          // No idle block means an older server, or a response we could not
          // read: say the one thing that is certainly true rather than nothing.
          <EmptyState
            title="Not in a game right now"
            body="This page checks again every minute while it is open."
          />
        ))}
      {data?.in_game && data.game && (
        <GameView
          game={data.game}
          platform={platform}
          you={data.puuid}
          stale={query.isError}
          poll={poll}
        />
      )}
      </div>
    </div>
  )
}

/**
 * The moment after a game ends, which is when a reader is most interested and
 * where this page used to stop with a paragraph telling them to go and look
 * somewhere else.
 *
 * Riot publishes a finished match a minute or two later, so the page asks for
 * it: at most three times, a minute apart, and the server bounds the spend at
 * three Riot calls per match id however many people are watching. Once it
 * lands, the result and a link to the full scoreboard replace the waiting.
 */
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
  const queryClient = useQueryClient()
  const [since] = useState(() => Date.now())
  // One ticking clock, so the wait can be shown and the asking can stop without
  // reading the wall clock during a render.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  // Bounded by elapsed time rather than by a counter: one minute per attempt,
  // three attempts. A fast poll on a forgotten tab is how the page that most
  // needs to stay inside the rate limit would spend it.
  const keepAsking = now - since < RESULT_ATTEMPTS * 60_000

  const result = useQuery({
    queryKey: ['live-result', game.match_id],
    queryFn: () => api.liveResult(platform, name, tag, game.match_id),
    refetchInterval: (query) =>
      query.state.data?.status === 'pending' && keepAsking ? 60_000 : false,
    retry: false,
  })

  const status = result.data?.status

  // The new game belongs in their history too, so the overview does not show a
  // stale list when the reader goes back to it.
  useEffect(() => {
    if (status === 'stored') {
      queryClient.invalidateQueries({ queryKey: ['matches', platform, name, tag] })
    }
  }, [status, queryClient, platform, name, tag])

  const waited = Math.max(0, Math.round((now - since) / 1000))

  return (
    <div className="space-y-5">
      {status === 'stored' ? (
        <StatusBand
          accent="var(--color-gold)"
          title={
            <span
              style={{
                color:
                  result.data?.win == null
                    ? 'var(--color-gold-bright)'
                    : result.data.win
                      ? 'var(--color-win)'
                      : 'var(--color-loss)',
              }}
            >
              {result.data?.win == null
                ? 'The result is in'
                : result.data.win
                  ? 'You won'
                  : 'You lost'}
              {result.data?.game_duration ? ` in ${duration(result.data.game_duration)}` : ''}
            </span>
          }
          detail={
            <>
              {/* Never a 0.0: a game the score was withheld for says nothing
                  about the score, the way the scoreboard already does. */}
              {result.data?.score != null && (
                <>
                  <span
                    className="tnum font-600"
                    style={{ color: scoreColor(result.data.score) }}
                  >
                    {result.data.score.toFixed(1)}
                  </span>{' '}
                  Riftline score
                  {result.data.placement != null && `, ${ordinal(result.data.placement)} of ten`}
                  {'. '}
                </>
              )}
              The scoreboard has gold, items and K/D/A for all ten players.
            </>
          }
          aside={
            <Link
              to={`/match/${encodeURIComponent(game.match_id)}?player=${encodeURIComponent(you)}`}
              className="control px-3 py-1.5 text-sm font-600 text-gold-bright"
            >
              Open the scoreboard
            </Link>
          }
        />
      ) : (
        <StatusBand
          accent="var(--color-gold)"
          title="This game has ended"
          detail={
            status === 'gave_up'
              ? 'Riot has not published this game. That happens when a game was remade, or was not a queue Riot publishes.'
              : `Riot publishes the result a minute or two later. This page is watching for it, ${waited < 60 ? `${waited}s` : `${Math.floor(waited / 60)}m`} so far.`
          }
          aside={
            status === 'gave_up' ? null : <Spinner label="Waiting for Riot" />
          }
        />
      )}

      {/* The lineup as it started. Collapsed once the scoreboard exists, which
          is strictly better, but kept because somebody will want to compare. */}
      {status === 'stored' ? (
        <details className="frame px-4 py-3">
          <summary className="cursor-pointer text-sm text-ink-dim">
            The lineup as the game started
          </summary>
          <div className="mt-4 opacity-70">
            <GameView game={game} platform={platform} you={you} stale={false} ended />
          </div>
        </details>
      ) : (
        <div className="opacity-70">
          <GameView game={game} platform={platform} you={you} stale={false} ended />
        </div>
      )}
    </div>
  )
}
