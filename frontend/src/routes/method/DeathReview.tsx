import type { MethodReport } from '../../lib/api'
import { compact, pct } from '../../lib/format'
import { Aside, B, Explainer, Prose, Section } from './shared'

export default function DeathReview() {
  return (
    <Explainer
      slug="death-review"
      eyebrow="The death review"
      title="The death review"
      intro={
        <>
          A death count says how often a player died. It does not say whether the deaths mattered. The
          death review reads each death and each takedown against what happened in the next minute and
          against the win-chance model, and says which were traded, which were converted, and what each
          cost.
        </>
      }
    >
      {(report) => <Body report={report} />}
    </Explainer>
  )
}

function Body({ report }: { report: MethodReport }) {
  const { review } = report
  const traded = review.deaths > 0 ? review.traded / review.deaths : null
  const converted = review.takedowns > 0 ? review.converted / review.takedowns : null
  return (
    <>
      <Section id="rules" title="The four rules">
        <Prose>
          The review is rules, not a model, and the rules are short enough to check against any game.
        </Prose>
        <dl className="max-w-prose space-y-3 text-sm leading-relaxed">
          <div>
            <dt className="font-600 text-ink">Traded</dt>
            <dd className="text-ink-dim">
              A death is traded when the dying player&apos;s team gains a kill, an epic monster, a tower, an
              inhibitor or a plate within {review.trade_seconds} seconds. The rest are untraded: the team got
              nothing for them. A death that bought a Baron is a trade; a death in the river to nobody&apos;s
              benefit is not.
            </dd>
          </div>
          <div>
            <dt className="font-600 text-ink">Converted</dt>
            <dd className="text-ink-dim">
              A takedown is converted when the player&apos;s team takes an epic monster or a building within{' '}
              {review.trade_seconds} seconds of it. A kill that turned into a tower is worth more than a kill
              that turned into a recall, and the rule says which was which.
            </dd>
          </div>
          <div>
            <dt className="font-600 text-ink">Cost and gain</dt>
            <dd className="text-ink-dim">
              Every death carries the win chance it took from the team and every takedown the win chance it
              gave, read from the win-chance model at that moment with the kill&apos;s bounty included. The
              victim&apos;s loss and the takers&apos; gain are the same number, seen from each side.
            </dd>
          </div>
          <div>
            <dt className="font-600 text-ink">Contested</dt>
            <dd className="text-ink-dim">
              An epic monster is contested when players from both teams are credited on it. A profile shows
              how many of a player&apos;s contested objectives their team took.
            </dd>
          </div>
        </dl>
      </Section>

      <Section id="why" title="Why these rules">
        <Prose>
          The trade rule follows the idea of a &ldquo;worthless death&rdquo; used in professional analysis:
          a 2025 study of 37,388 professional games found it among the measures that best separated
          players, ahead of raw deaths. The cost rule follows Maymin&apos;s 2020 finding that kills and deaths
          weighed by the win probability they moved track team results far more closely than a plain kill
          to death ratio. Both say the same thing from different directions: what a death cost depends on
          when and why it happened, and a count throws that away.
        </Prose>
        <Prose>
          The minute is a judgement. Shorter, and a death that set up a Baron 70 seconds later reads as
          wasted; longer, and the next unrelated fight is credited to it. Sixty seconds is where the
          examples read right most often on our games, and it is stated so that a reader who disagrees can
          see exactly what they disagree with.
        </Prose>
      </Section>

      <Section id="corpus" title="What our games show">
        {review.deaths > 0 ? (
          <Prose>
            Across <B>{compact(review.games)}</B> ranked games and <B>{compact(review.deaths)}</B> deaths,{' '}
            <B>{traded !== null ? pct(traded, 1) : '-'}</B> of deaths were traded and{' '}
            <B>{converted !== null ? pct(converted, 1) : '-'}</B> of <B>{compact(review.takedowns)}</B>{' '}
            takedowns were converted. Of <B>{compact(review.contests)}</B> contested objectives,{' '}
            <B>{compact(review.contests_won)}</B> went to the player&apos;s team, which is close to half
            because every contest has a team on each side. Those rates are the baseline a profile is read
            against: a player whose deaths are traded 80% of the time is doing better than most.
          </Prose>
        ) : (
          <Prose>The review runs every night once the win-chance model is published; the figures appear then.</Prose>
        )}
      </Section>

      <Section id="profile" title="How a profile is placed">
        <Prose>
          A profile shows four rates: untraded deaths as a share of deaths, win chance lost per 30 minutes,
          converted takedowns as a share of takedowns, and win chance gained per 30 minutes. Each of a
          player&apos;s games is placed against every game Riftline holds in the same role, as a percentile,
          and the percentiles are averaged, the same way the Riftline score is built. &ldquo;Better than
          64% of mid laners&rdquo; means the same thing on every profile. For the two rates where lower is
          better, the percentile is turned around, so higher is always better on the bar.
        </Prose>
        <Prose>
          The rates are withheld until <B>{review.min_profile_games}</B> reviewed games in a role stand
          behind them. Three games place nobody: one death in the river would move the untraded rate by a
          third.
        </Prose>
      </Section>

      <Section id="limits" title="Where it is wrong">
        <Prose>
          The trade rule is at team level. If a teammate on the other side of the map takes a tower thirty
          seconds after a pointless death, that death reads as traded, because the rule cannot tell a trade
          from a coincidence. The cost of a death comes from a model that cannot see items, positions or
          respawn timers, so a death at 35 minutes with Baron up costs the same as one with Baron down.
          Only ranked solo and flex games with a stored timeline are reviewed, and a profile&apos;s rates
          describe those games, not a whole season. When the model is refitted with a change in what it
          reads, every review is recomputed against the new version, so figures can move a little from
          one night to the next without any game changing.
        </Prose>
        <Aside>
          Everything above is a rule that can be checked on a game page. Open a game&apos;s story, pick a
          player, and each death is listed with what happened in the minute after it and what the model
          says it cost.
        </Aside>
      </Section>
    </>
  )
}
