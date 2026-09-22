import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import { ErrorView, Spinner } from '../components/StateViews'
import { api, type AuditRole, type MethodReport, type WinModelMethod } from '../lib/api'
import { compact, pct, positionLabel } from '../lib/format'

const ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']

/**
 * Every number the site makes itself, and how well it holds up.
 *
 * The Riftline score's weights and how well they track wins; the win-chance
 * model's features, accuracy and calibration on games it had not seen; the
 * death review's rules and what they produce; the lane labels' cut points.
 * Competitors publish none of this. It is here so a reader can decide how far
 * to trust each number, including when the answer is "not far".
 */
export default function Method() {
  const query = useQuery({ queryKey: ['method'], queryFn: api.method, staleTime: 10 * 60 * 1000 })
  const location = useLocation()

  // The router does not scroll to a #section on its own, and the sections
  // only exist once the report has loaded.
  useEffect(() => {
    if (!query.data || !location.hash) return
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ block: 'start' })
  }, [query.data, location.hash])

  return (
    <div>
      <ArtHeader>
        <p className="eyebrow">Method</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          How our numbers are made
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          The score, the win chance, the death review and the lane labels are ours, not Riot's.
          Here is how each is made, measured on our own games, and how well it holds up.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1080px] space-y-12 px-4 py-8">
        {query.isLoading && <Spinner label="Loading the method" />}
        {query.isError && <ErrorView error={query.error} onRetry={() => query.refetch()} />}
        {query.data && (
          <>
            <ScoreSection report={query.data} />
            <WinChanceSection model={query.data.win_model} />
            <ReviewSection review={query.data.review} />
            <LaneSection lanes={query.data.lanes} />
          </>
        )}
      </div>
    </div>
  )
}

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 space-y-4">
      <h2 id={`${id}-title`} className="display text-2xl font-700 text-ink">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Prose({ children }: { children: React.ReactNode }) {
  return <p className="max-w-prose text-sm leading-relaxed text-ink-dim">{children}</p>
}

// ------------------------------------------------------------------ the score

function ScoreSection({ report }: { report: MethodReport }) {
  const { score } = report
  const audit = score.audit
  return (
    <Section id="score" title="The Riftline score">
      <Prose>
        Each component is a percentile against the same role in our games, and the score is their
        weighted mean on a scale of 0 to 10. The weights are set by hand and published here, and
        withheld from a role until {score.min_games.toLocaleString()} games stand behind it.
      </Prose>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-xs text-ink-faint">
              <th className="py-1.5 pr-3 text-left font-500">Component</th>
              {ROLES.map((r) => (
                <th key={r} className="py-1.5 pl-2 text-right font-500">
                  {positionLabel(r)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {score.components.map((c) => (
              <tr key={c.id} className="border-b border-line-soft">
                <td className="py-1.5 pr-3">
                  <span className="text-ink">{c.label}</span>
                  <span className="block text-xs text-ink-faint">{c.measures}</span>
                </td>
                {ROLES.map((r) => (
                  <td key={r} className="tnum py-1.5 pl-2 text-right text-ink-dim">
                    {pct(score.weights[r]?.[c.id] ?? 0)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="display pt-2 text-lg font-600 text-ink">How well it tracks wins</h3>
      {!audit ? (
        <Prose>The audit of these weights has not run yet; it runs every night.</Prose>
      ) : (
        <>
          <Prose>
            On {compact(audit.games)} of our ranked solo games, winners averaged{' '}
            <b className="text-ink">{audit.overall.winners_mean?.toFixed(2)}</b> and losers{' '}
            <b className="text-ink">{audit.overall.losers_mean?.toFixed(2)}</b>. A random winner
            outscored a random loser{' '}
            <b className="text-ink">{audit.overall.auc !== null ? pct(audit.overall.auc) : '-'}</b>{' '}
            of the time (the AUC: 50% is a coin, 100% perfect). The lobby's top scorer was on the
            winning team{' '}
            <b className="text-ink">
              {audit.overall.top_on_winning_team !== null ? pct(audit.overall.top_on_winning_team, 1) : '-'}
            </b>{' '}
            of the time, and the bottom scorer on the losing team{' '}
            <b className="text-ink">
              {audit.overall.bottom_on_losing_team !== null ? pct(audit.overall.bottom_on_losing_team, 1) : '-'}
            </b>
            .
          </Prose>
          <div className="grid gap-5 md:grid-cols-2">
            {audit.roles.map((role) => (
              <AuditCard key={role.position} role={role} components={score.components} />
            ))}
          </div>
          <p className="max-w-prose border-l-2 border-gold/50 py-1 pl-3 text-sm leading-relaxed text-ink-dim">
            The fitted weights are what a fit to wins would choose. They are not adopted: winners
            take objectives, earn gold and stay alive partly because they are already winning, so
            a fit to wins rewards being on the winning team, and it puts kill participation, damage
            share and vision at nothing. They are here as a check on the hand-set weights, not a
            replacement for them.
          </p>
        </>
      )}
    </Section>
  )
}

function AuditCard({
  role,
  components,
}: {
  role: AuditRole
  components: { id: string; label: string }[]
}) {
  const peak = Math.max(...role.deciles.map((d) => d.win_rate), 0.01)
  return (
    <div className="frame space-y-3 px-4 py-3">
      <div className="flex items-baseline justify-between">
        <h4 className="display text-base font-600 text-ink">{positionLabel(role.position)}</h4>
        <span className="tnum text-xs text-ink-faint">
          AUC {role.auc !== null ? pct(role.auc) : '-'}, {compact(role.players)} players
        </span>
      </div>
      <div>
        <p className="mb-1 text-xs text-ink-faint">Win rate by score tenth, lowest to highest</p>
        <div className="flex h-16 items-end gap-1" role="img" aria-label={`Win rate by decile: ${role.deciles.map((d) => pct(d.win_rate)).join(', ')}`}>
          {role.deciles.map((d, i) => (
            <span
              key={i}
              className="flex-1 rounded-t-sm"
              style={{ height: `${(d.win_rate / peak) * 100}%`, background: 'var(--accent)', opacity: 0.35 + 0.65 * d.win_rate }}
              title={`Scores ${d.low} to ${d.high}: ${pct(d.win_rate)} won, ${d.games} players`}
            />
          ))}
        </div>
      </div>
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="text-ink-faint">
            <th className="py-0.5 text-left font-500">Component</th>
            <th className="py-0.5 text-right font-500">Set</th>
            <th className="py-0.5 text-right font-500">Fitted</th>
          </tr>
        </thead>
        <tbody>
          {components.map((c) => (
            <tr key={c.id} className="border-t border-line-soft">
              <td className="py-0.5 text-ink-dim">{c.label}</td>
              <td className="tnum py-0.5 text-right text-ink">{pct(role.set_weights[c.id] ?? 0)}</td>
              <td className="tnum py-0.5 text-right text-ink-faint">{pct(role.fitted.normalised[c.id] ?? 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// -------------------------------------------------------------- the win chance

function WinChanceSection({ model }: { model: WinModelMethod | null }) {
  if (!model) {
    return (
      <Section id="win-chance" title="The win chance">
        <Prose>The win-chance model has not been trained yet. It is fitted every night.</Prose>
      </Section>
    )
  }
  const overall = model.cv.overall
  return (
    <Section id="win-chance" title="The win chance">
      <Prose>
        A game's story draws each side's chance to win from a logistic regression on the game
        state, blue minus red: gold, kills, towers, inhibitors down, dragons, the dragon soul, the
        Elder and Baron buffs, Voidgrubs, the Rift Herald, Atakhan and levels. Each feature has a
        weight at minute 0 and at minute 40, and the effect moves in a straight line between them. No feature may count against the side that holds it. It was trained on{' '}
        {compact(model.trained_games)} of our ranked solo games ({compact(model.trained_rows)}{' '}
        game-minutes) and is refitted every night.
      </Prose>
      {!model.published && (
        <p className="border-l-2 border-loss/60 py-1 pl-3 text-sm text-ink-dim">
          Withheld from game pages: {model.withheld}.
        </p>
      )}
      {overall && (
        <>
          <Prose>
            Graded on games it had not seen, five folds split by game: it called the winner{' '}
            <b className="text-ink">{pct(overall.accuracy, 1)}</b> of the time, with a Brier score of{' '}
            <b className="text-ink">{overall.brier.toFixed(3)}</b> against{' '}
            {overall.baseline_brier.toFixed(3)} for always guessing blue's win rate. Its calibration
            error is <b className="text-ink">{((model.cv.ece ?? 0) * 100).toFixed(1)} points</b>. Game
            pages show it only while it removes at least{' '}
            {((model.gate.min_skill ?? 0) * 100).toFixed(0)}% of that guess's error and its
            calibration error stays under {((model.gate.max_ece ?? 0) * 100).toFixed(0)} points.
          </Prose>
          <div className="grid items-start gap-6 md:grid-cols-2">
            <table className="w-full border-collapse text-sm">
              <caption className="mb-1 text-left text-xs text-ink-faint">By game time</caption>
              <thead>
                <tr className="border-b border-line text-xs text-ink-faint">
                  <th className="py-1 text-left font-500">Minutes</th>
                  <th className="py-1 text-right font-500">Right</th>
                  <th className="py-1 text-right font-500">Brier</th>
                  <th className="py-1 text-right font-500">Game-minutes</th>
                </tr>
              </thead>
              <tbody>
                {(model.cv.phases ?? []).map((p) => (
                  <tr key={p.label} className="border-b border-line-soft">
                    <td className="py-1 text-ink-dim">{p.label}</td>
                    <td className="tnum py-1 text-right text-ink">{pct(p.accuracy, 1)}</td>
                    <td className="tnum py-1 text-right text-ink-dim">{p.brier.toFixed(3)}</td>
                    <td className="tnum py-1 text-right text-ink-faint">{compact(p.rows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <table className="w-full border-collapse text-sm">
              <caption className="mb-1 text-left text-xs text-ink-faint">
                When it said this, the side won this often
              </caption>
              <thead>
                <tr className="border-b border-line text-xs text-ink-faint">
                  <th className="py-1 text-left font-500">Said</th>
                  <th className="py-1 text-left font-500">Happened</th>
                  <th className="py-1 text-right font-500">Game-minutes</th>
                </tr>
              </thead>
              <tbody>
                {(model.cv.reliability ?? []).map((b) => (
                  <tr key={b.low} className="border-b border-line-soft">
                    <td className="tnum py-1 text-ink-dim">{pct(b.predicted)}</td>
                    <td className="py-1">
                      <span className="flex items-center gap-2">
                        <span className="tnum w-9 text-ink">{pct(b.observed)}</span>
                        <span className="relative h-1.5 flex-1 rounded-full bg-raised" aria-hidden>
                          <span className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${b.observed * 100}%`, background: 'var(--accent)' }} />
                          <span className="absolute -inset-y-0.5 w-px bg-ink" style={{ left: `${b.predicted * 100}%` }} />
                        </span>
                      </span>
                    </td>
                    <td className="tnum py-1 text-right text-ink-faint">{compact(b.rows)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {model.effects.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <caption className="mb-1 text-left text-xs text-ink-faint">
              What one more of each is worth, in points of win chance, from an even game
            </caption>
            <thead>
              <tr className="border-b border-line text-xs text-ink-faint">
                <th className="py-1 text-left font-500">Lead</th>
                <th className="py-1 text-right font-500">At 10 min</th>
                <th className="py-1 text-right font-500">At 20 min</th>
                <th className="py-1 text-right font-500">At 30 min</th>
              </tr>
            </thead>
            <tbody>
              {model.effects.map((e) => (
                <tr key={e.feature} className="border-b border-line-soft">
                  <td className="py-1 text-ink-dim">
                    {e.label} <span className="text-xs text-ink-faint">({e.unit})</span>
                  </td>
                  {['10', '20', '30'].map((m) => {
                    const value = e.points[m]
                    return (
                      <td key={m} className="tnum py-1 text-right text-ink">
                        {value === null || value === undefined ? (
                          <span className="text-xs text-ink-faint">Not seen</span>
                        ) : value > 0 ? (
                          `+${value.toFixed(1)}`
                        ) : (
                          value.toFixed(1)
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Prose>
        What it cannot see: items, champions, who is dead or where anyone stands, and respawn
        timers. A tower or a Baron is worth little on its own here because the model credits it
        through the gold and buildings that follow, which is why a game's moments are measured on
        the curve from just before a fight to a minute after.
      </Prose>
    </Section>
  )
}

// -------------------------------------------------------------- the review

function ReviewSection({ review }: { review: MethodReport['review'] }) {
  return (
    <Section id="review" title="The death review">
      <ul className="max-w-prose list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-ink-dim">
        <li>
          A death is <b className="text-ink">traded</b> when the team gets a kill, an epic monster, a
          tower, an inhibitor or a plate back within {review.trade_seconds} seconds. The rest are
          untraded: the team got nothing for them.
        </li>
        <li>
          A takedown is <b className="text-ink">converted</b> when the team takes an epic monster or
          a building within {review.trade_seconds} seconds.
        </li>
        <li>
          Each is weighed by what it did to the team's chance to win, from the model above. The
          victim's loss and the takers' gain are the same number.
        </li>
        <li>
          An objective is <b className="text-ink">contested</b> when players from both teams are
          credited on it.
        </li>
      </ul>
      {review.deaths > 0 && (
        <Prose>
          On {compact(review.games)} of our ranked games,{' '}
          <b className="text-ink">{pct(review.traded / review.deaths, 1)}</b> of{' '}
          {compact(review.deaths)} deaths were traded and{' '}
          <b className="text-ink">{pct(review.converted / Math.max(1, review.takedowns), 1)}</b> of{' '}
          {compact(review.takedowns)} takedowns converted.
        </Prose>
      )}
      <Prose>
        A profile places a player's rates against the same role, as a percentile per game averaged
        over their games, and only from {review.min_profile_games} reviewed games in that role.
      </Prose>
    </Section>
  )
}

// -------------------------------------------------------------- lanes

function LaneSection({ lanes }: { lanes: MethodReport['lanes'] }) {
  return (
    <Section id="lanes" title="Lane labels">
      <Prose>
        A lane's result at 14 minutes is its share of the pair's gold, experience and CS. How far
        from even that share sits is placed against the same role: the closest{' '}
        {pct(lanes.even_below)} of lanes are even, the widest {pct(1 - lanes.big_from)} are won or
        lost big, and the rest won or lost. A role with fewer than {lanes.min_games} measured lanes
        gets no labels.
      </Prose>
    </Section>
  )
}
