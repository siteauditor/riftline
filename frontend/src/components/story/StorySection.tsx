import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../../lib/api'
import { pct } from '../../lib/format'
import { ErrorView, Spinner } from '../StateViews'
import DeathReview from './DeathReview'
import Moments from './Moments'
import WinChanceCurve from './WinChanceCurve'

/**
 * How a game went: each side's chance to win over time, the moments that
 * decided it, and one player's deaths and takedowns weighed.
 *
 * The one part of a match page that may call Riot: a game fetched for a
 * profile has no timeline until the nightly run, and opening its story fetches
 * that timeline once. On a busy key the section says so and offers a retry
 * rather than failing the page.
 */
export default function StorySection({
  matchId,
  subjectPuuid,
}: {
  matchId: string
  subjectPuuid: string
}) {
  const query = useQuery({
    queryKey: ['story', matchId],
    queryFn: () => api.matchStory(matchId),
    // A story never changes once read; a pending one is asked again on demand.
    staleTime: Infinity,
    retry: false,
  })

  if (query.isLoading) {
    return (
      <div className="frame px-4 py-6">
        <Spinner label="Reading the game's timeline" />
      </div>
    )
  }
  if (query.isError || !query.data) {
    return (
      <div className="frame px-4 py-4">
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const story = query.data
  if (!story.available) {
    return (
      <div className="frame flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm text-ink-dim">
        <p>
          <span className="text-ink">No story for this game yet.</span> {story.reason}
          {story.pending && story.retry_after !== null &&
            ` Try again in about ${Math.max(1, Math.ceil(story.retry_after))} seconds.`}
        </p>
        {story.pending && (
          <button
            type="button"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
            className="rounded-sm border border-line px-3 py-1.5 text-xs text-ink-dim transition-colors hover:border-gold hover:text-gold-bright disabled:opacity-50"
          >
            {query.isFetching ? 'Trying' : 'Try again'}
          </button>
        )}
      </div>
    )
  }

  const subject = story.players.find((p) => p.puuid === subjectPuuid) ?? null
  // The viewer's side: the player the page is about, or blue with nobody named.
  const team = subject?.team_id ?? 100
  const won = story.blue_won === null ? null : team === 100 ? story.blue_won : !story.blue_won
  const model = story.model
  const published = Boolean(model?.published)
  const early = model?.phases[0]

  return (
    <section className="frame space-y-6 px-4 py-5" aria-labelledby="story-heading">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h2 id="story-heading" className="display text-xl font-700 text-ink">
          How this game went
        </h2>
        {published && model && (
          <p className="max-w-[60ch] text-xs leading-relaxed text-ink-faint">
            {subject ? 'Your' : "Blue side's"} chance to win, from a model trained on{' '}
            {model.trained_games.toLocaleString()} of our ranked solo games
            {story.queue_id === 440 ? ' (this is a flex game)' : ''}. On games it had not seen it
            called the winner {model.accuracy !== null ? pct(model.accuracy) : ''} of the time
            {early ? `, ${pct(early.accuracy)} in the first ten minutes` : ''}.{' '}
            <Link to="/method#win-chance" className="underline decoration-line underline-offset-2 hover:text-gold-bright">
              How it works
            </Link>
          </p>
        )}
      </header>

      {published && story.curve.length > 1 ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <WinChanceCurve
            curve={story.curve}
            team={team}
            moments={story.moments}
            durationMs={story.duration_ms}
            won={won}
          />
          <div className="min-w-0">
            <h3 className="display text-base font-600 text-ink">The moments that decided it</h3>
            <p className="mb-3 mt-0.5 text-xs text-ink-faint">
              Biggest first, numbered as on the curve: the change in win chance from just before
              each to a minute after.
              {subject && ` ${subject.champion.name} was on the ${team === 100 ? 'blue' : 'red'} side.`}
            </p>
            <Moments moments={story.moments} team={team} />
          </div>
        </div>
      ) : (
        <p className="border-l-2 border-gold/50 py-1 pl-3 text-sm text-ink-dim">
          No win-chance curve. {story.reason} Trades and conversions below are rules, not the
          model, so they are shown anyway.
        </p>
      )}

      <DeathReview
        players={story.players}
        subjectIndex={subject?.participant_index ?? null}
        mapUrl={story.map_url}
        published={published}
      />
    </section>
  )
}
