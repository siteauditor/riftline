import { useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import { ErrorView, Spinner } from '../components/StateViews'
import { compact, pct } from '../lib/format'
import { heads } from '../lib/seo'
import { EXPLAINERS, useMethod } from './method/data'

/**
 * Every number the site makes itself, and how well it holds up.
 *
 * A hub: one paragraph and one live figure per method, and a page for each
 * that says how it is made, what it was measured against and where it fails.
 * Competitors publish none of this. It is here so a reader can decide how far
 * to trust each number, including when the answer is "not far".
 */
export default function Method() {
  const query = useMethod()
  const location = useLocation()
  const navigate = useNavigate()

  // The sections used to live on this page under #score, #win-chance, #review
  // and #lanes, and those links are out there. Each is now its own page.
  useEffect(() => {
    const target: Record<string, string> = {
      score: '/method/score',
      'win-chance': '/method/win-chance',
      review: '/method/death-review',
      lanes: '/method/lane-labels',
    }
    const next = target[location.hash.slice(1)]
    if (next) navigate(next, { replace: true })
  }, [location.hash, navigate])

  const report = query.data
  const audit = report?.score.audit
  const model = report?.win_model
  const review = report?.review

  const figures: Record<string, string | null> = {
    score: audit?.overall.auc != null ? `AUC ${pct(audit.overall.auc)} on ${compact(audit.games)} games` : null,
    'win-chance':
      model?.cv.overall ? `${pct(model.cv.overall.accuracy, 1)} of winners called on games it had not seen` : null,
    'death-review':
      review && review.deaths > 0 ? `${pct(review.traded / review.deaths, 1)} of ${compact(review.deaths)} deaths traded` : null,
    'lane-labels': report ? `the closest ${pct(report.lanes.even_below)} of lanes are even` : null,
  }

  return (
    <div>
      <Head {...heads.method()} />
      <ArtHeader>
        <p className="eyebrow">Method</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          How our numbers are made
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          The score, the win chance, the death review and the lane labels are ours, not Riot&apos;s.
          Each has a page that says how it is made, what it was measured against on our own games,
          and where it goes wrong. The figures are recomputed every night and published whether they
          flatter the method or not.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1080px] space-y-8 px-4 py-8">
        {query.isLoading && <Spinner label="Loading the figures" />}
        {query.isError && <ErrorView error={query.error} onRetry={() => query.refetch()} />}

        <ul className="grid gap-4 md:grid-cols-2">
          {EXPLAINERS.map((e) => (
            <li key={e.slug} className="frame">
              <Link to={`/method/${e.slug}`} className="lift block px-4 py-4">
                <h2 className="display text-xl font-700 text-ink">{e.title}</h2>
                <p className="mt-1 text-sm leading-relaxed text-ink-dim">{e.short}</p>
                {figures[e.slug] && (
                  <p className="tnum mt-3 text-xs text-ink-faint">Tonight: {figures[e.slug]}.</p>
                )}
              </Link>
            </li>
          ))}
        </ul>

        <section className="max-w-prose space-y-3 text-sm leading-relaxed text-ink-dim">
          <h2 className="display text-xl font-700 text-ink">What all four have in common</h2>
          <p>
            Each is computed from the games Riftline stores, never from a black box, and each is
            withheld rather than guessed when the games behind it are too few: a score needs{' '}
            {report ? report.score.min_games.toLocaleString('en-US') : 'hundreds of'} games in a queue and
            role, a profile average needs {report ? report.review.min_profile_games : 'ten'} scored games,
            and the win-chance curve is shown only while it beats a plain guess by a stated margin.
          </p>
          <p>
            None of them is a rating of a player. Riot&apos;s rank is the only ranking on this site, shown
            beside these numbers and never combined with them.
          </p>
        </section>
      </div>
    </div>
  )
}
