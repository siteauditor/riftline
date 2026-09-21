import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import PositionIcon from '../components/PositionIcon'
import Scoreboard from '../components/match/Scoreboard'
import { ErrorView, Spinner } from '../components/StateViews'
import { api } from '../lib/api'
import { duration, ordinal, parseRiotId, positionLabel, scoreColor } from '../lib/format'
import { useChampionArt } from '../lib/useChampionArt'

/**
 * One stored game on its own page.
 *
 * The home page links a week's best games here, and a week-old game is usually
 * not in the player's latest twenty, so the scoreboard that match history
 * expands in place had nowhere to open. `?player=` names whose game it is: that
 * row is highlighted and the header is about them.
 */
export default function Match() {
  const { matchId = '' } = useParams()
  const [search] = useSearchParams()
  const subjectPuuid = search.get('player') ?? ''

  // The same key the scoreboard uses, so it renders from this response rather
  // than asking again.
  const query = useQuery({
    queryKey: ['match', matchId],
    queryFn: () => api.matchDetail(matchId),
    staleTime: Infinity,
    retry: false,
  })

  // Read before the loading and error branches: a hook cannot run only
  // sometimes. The subject is the player the link named, so the art is theirs.
  const heroArt = useChampionArt(
    query.data?.teams.flat().find((p) => p.puuid === subjectPuuid)?.champion.id,
  )

  if (query.isLoading) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-16">
        <Spinner label="Loading the game" />
      </div>
    )
  }
  if (query.isError || !query.data) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 py-16">
        <ErrorView error={query.error} onRetry={() => query.refetch()} />
      </div>
    )
  }

  const detail = query.data
  const platform = (detail.platform ?? matchId.split('_')[0]).toLowerCase()
  const subject = detail.teams.flat().find((p) => p.puuid === subjectPuuid)
  const riotId = subject?.riot_id ? parseRiotId(subject.riot_id) : null
  const played = new Date(detail.game_creation).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })

  return (
    <div>
      <ArtHeader art={heroArt}>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="display text-[clamp(1.9rem,4.5vw,2.9rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
            {subject && riotId ? (
              <>
                <Link
                  to={`/summoner/${platform}/${encodeURIComponent(riotId.name)}/${encodeURIComponent(riotId.tag)}`}
                  className="transition-colors hover:text-gold-bright"
                >
                  {riotId.name}
                </Link>{' '}
                <span className="text-ink-dim">on {subject.champion.name}</span>
              </>
            ) : (
              detail.queue_name
            )}
          </h1>
          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-dim">
            {subject?.position && (
              <span className="inline-flex items-center gap-1">
                <PositionIcon position={subject.position} className="size-4" />
                {positionLabel(subject.position)}
              </span>
            )}
            {subject && (
              <span className={subject.win ? 'text-win' : 'text-loss'}>
                {subject.win ? 'Win' : 'Loss'}
              </span>
            )}
            {subject && <span>{detail.queue_name}</span>}
            <span>{played}</span>
            <span className="tnum">{duration(detail.game_duration)}</span>
            {detail.patch && <span>Patch {detail.patch}</span>}
          </p>
        </div>

        {subject?.score != null && (
          <div className="text-right">
            <span
              className="tnum display block text-5xl font-700 leading-none"
              style={{ color: scoreColor(subject.score) }}
            >
              {subject.score.toFixed(1)}
            </span>
            <span className="mt-1 block text-xs text-ink-faint">
              Riftline score
              {subject.placement != null && `, ${ordinal(subject.placement)} of 10`}
            </span>
          </div>
        )}
      </div>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">
      <div className="frame">
        <Scoreboard matchId={matchId} subjectPuuid={subjectPuuid} platform={platform} />
      </div>
      </div>
    </div>
  )
}
