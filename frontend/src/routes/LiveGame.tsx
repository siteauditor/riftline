import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api, type LiveGame } from '../lib/api'
import ArtHeader from '../components/ArtHeader'
import GameView from '../components/live/GameView'
import ProfileTabs from '../components/ProfileTabs'
import { EmptyState, ErrorView, Spinner } from '../components/StateViews'
import { useChampionArt } from '../lib/useChampionArt'

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
  const heroArt = useChampionArt(
    shown?.participants.find((p) => p.puuid && p.puuid === data?.puuid)?.champion.id,
  )

  // One shell around every branch, matching the other routes: without it the
  // page sits flush against the viewport edge while the header stays centred.
  return (
    <div>
      {/* The same header the other two tabs carry. Without it this page was a
          strip of tabs and an empty box, with nothing saying whose it was. */}
      <ArtHeader art={heroArt}>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <div className="min-w-0">
            <p className="eyebrow">Live game</p>
            <h1 className="display mt-1 text-[clamp(1.9rem,4.5vw,2.9rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
              {name}
              <span className="ml-2 text-[0.5em] font-600 text-ink-faint">#{tag}</span>
            </h1>
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
