import type { AuditRole, MethodReport } from '../../lib/api'
import { compact, pct, positionLabel } from '../../lib/format'
import { Aside, B, Explainer, Prose, Section } from './shared'

const ROLES = ['TOP', 'JUNGLE', 'MIDDLE', 'BOTTOM', 'UTILITY']

/** Each component in the order the table shows them, and what it is for. */
const WHY: Record<string, string> = {
  kill_part:
    'Kills and assists as a share of the team’s kills. It says whether a player was where the fights were, ' +
    'which is why it is the biggest weight for a support and a jungler.',
  damage:
    'The player’s share of the team’s damage to champions. A share, so it is fair across game lengths, ' +
    'and unfair to a player whose team did nothing, which the next component corrects for.',
  efficiency:
    'Damage to champions per 1,000 gold earned. The one number here that is the player’s own rather than ' +
    'a share of a team total: it asks what the gold became.',
  economy: 'Gold per minute: farm, kills and objectives, all in one rate.',
  survival:
    'The share of the game spent alive. Deaths are costed by time, not counted, so a death at minute 3 and a death ' +
    'at minute 35 weigh what they cost the team.',
  objectives: 'Towers, plates and epic monsters the player took part in.',
  vision: 'Vision score per minute, which is the component that lets a support score a 9.',
}

export default function Score() {
  return (
    <Explainer
      slug="score"
      eyebrow="The score"
      title="The Riftline score"
      intro={
        <>
          Every player in a ranked game gets a number from 0 to 10 for that game, a placement from 1 to 10
          in the lobby, and badges. It is our number, not Riot&apos;s. This page says exactly how it is
          made, and shows, in public and every night, how well it tracks winning.
        </>
      }
    >
      {(report) => <Body report={report} />}
    </Explainer>
  )
}

function Body({ report }: { report: MethodReport }) {
  const { score } = report
  const audit = score.audit
  return (
    <>
      <Section id="what" title="What the score is">
        <Prose>
          A performance score answers a question the scoreboard cannot: who played well, independently
          of who won. KDA cannot answer it, because a support who never dies and never kills has the same
          KDA as one who does nothing, and a jungler who takes every objective and dies doing it looks worse
          than one who farmed camps all game. The Riftline score measures seven things a player does, places
          each against players in the same role, and combines them with weights that are published on this
          page and never change without an audit.
        </Prose>
        <Prose>
          It is a score for one game, not a rating of a player. Ten games of it say something about a player;
          one game says something about that game. A profile averages it over a role, and only once{' '}
          <B>{report.review.min_profile_games}</B> scored games in that role stand behind the average,
          because below that one game moves the average by a full point.
        </Prose>
      </Section>

      <Section id="components" title="The seven components">
        <Prose>
          Each component becomes a percentile: where this game&apos;s value sits among every game
          Riftline holds in the same queue and the same role. Percentiles rather than standard scores,
          because damage and gold have long tails and one 40-minute stomp should not stretch the scale for
          everyone. Role-relative, so a support is never judged on farm and a top laner is never judged on
          vision, and so the ten scores in a lobby share one scale, which is what makes a placement mean
          anything.
        </Prose>
        <dl className="max-w-prose space-y-3 text-sm leading-relaxed">
          {score.components.map((c) => (
            <div key={c.id}>
              <dt className="font-600 text-ink">
                {c.label} <span className="font-400 text-ink-faint">({c.measures})</span>
              </dt>
              <dd className="text-ink-dim">{WHY[c.id] ?? c.measures}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section id="weights" title="The weights, by role">
        <Prose>
          The seven percentiles are combined with these weights and the result is put on a scale of 0 to
          10. The weights are set by hand, per role, and published here. A fit to wins would choose
          different ones, and the audit below shows what it would choose and why it is not adopted.
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
                  <td className="py-1.5 pr-3 text-ink">{c.label}</td>
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
        <Prose>
          Reading across a row: kill participation is a support&apos;s and a jungler&apos;s biggest weight,
          because being at the fights is most of their job; vision is a support&apos;s second; economy and
          survival are what a top laner is asked for. Reading down a column, a role&apos;s weights add up to
          one, so every role averages the same score across the corpus, which is the check that a support
          and a mid laner are measured on the same scale. This is version {score.version} of the weights.
        </Prose>
        <Aside>
          Version 2 added damage per gold. Kill participation and damage share are both shares of a team
          total, so a player on a team that did little looked good on them for doing a little more. Damage
          per gold is the player&apos;s own. It took its weight from damage share, the component it overlaps,
          and on the same games it raised the score&apos;s AUC from 0.720 to 0.731 and every role&apos;s
          AUC with it. Spreading the weight across four components instead did worse, so that table was not
          shipped.
        </Aside>
      </Section>

      <Section id="withheld" title="When there is no score">
        <Prose>
          A lobby without ten players in lane roles gets no score: ARAM and Arena have no lanes, so a
          role-relative measure has nothing to measure against. A remake gets none. A queue and role with
          fewer than <B>{score.min_games.toLocaleString('en-US')}</B> games in the corpus gets none either,
          because a percentile against 40 games describes those 40 games, not the player. In each case the
          match row shows a dash and says why, never a guess. A score is computed the moment a game is
          stored, so a profile&apos;s newest games carry one at once.
        </Prose>
      </Section>

      <Section id="badges" title="Badges">
        <Prose>
          Badges name what a score cannot: the tank who took a third of the team&apos;s damage and the
          enchanter who shielded thousands both look ordinary by KDA, which is exactly what the usual badges
          miss. Each badge is a rule, and the thresholds were swept against the corpus rather than picked.
        </Prose>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-xs text-ink-faint">
                <th className="py-1.5 pr-3 text-left font-500">Badge</th>
                <th className="py-1.5 text-left font-500">Rule</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['MVP', 'Highest Riftline score on the winning team'],
                ['ACE', 'Highest Riftline score on the losing team'],
                ['Steal', 'Stole a dragon, herald or baron from the enemy'],
                ['Deathless', 'Finished a game of 15 minutes or more without dying'],
                ['Frontline', 'Took the largest share of the team’s damage, and at least 30% of it'],
                ['Lifeline', 'Most healing and shielding that landed on allies in the lobby, and at least 5,000'],
                ['Lane lead', 'Biggest gold lead at 14 minutes in the lobby, and at least 2,000 gold'],
                ['Damage carry', 'Largest share of the team’s damage to champions, and at least 30% of it'],
                ['Duelist', 'Three or more solo kills'],
              ].map(([badge, rule]) => (
                <tr key={badge} className="border-b border-line-soft">
                  <td className="py-1.5 pr-3 font-600 text-ink">{badge}</td>
                  <td className="py-1.5 text-ink-dim">{rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="audit" title="How well it tracks wins">
        <Prose>
          A score that measures play should tend to be higher on the winning team without being a
          restatement of the result. Every night the score is graded on every ranked solo game Riftline
          holds, per role, and the grade is published here whether it is flattering or not.
        </Prose>
        {!audit ? (
          <Prose>The audit of these weights has not run yet; it runs every night.</Prose>
        ) : (
          <>
            <Prose>
              On <B>{compact(audit.games)}</B> games and <B>{compact(audit.players)}</B> scored players,
              winners averaged <B>{audit.overall.winners_mean?.toFixed(2)}</B> and losers{' '}
              <B>{audit.overall.losers_mean?.toFixed(2)}</B>. A random winner outscored a random loser{' '}
              <B>{audit.overall.auc !== null ? pct(audit.overall.auc) : '-'}</B> of the time: that is the
              AUC, where 50% is a coin and 100% would mean the score simply reads the result. The lobby&apos;s
              top scorer was on the winning team{' '}
              <B>{audit.overall.top_on_winning_team !== null ? pct(audit.overall.top_on_winning_team, 1) : '-'}</B>{' '}
              of the time and its bottom scorer on the losing team{' '}
              <B>{audit.overall.bottom_on_losing_team !== null ? pct(audit.overall.bottom_on_losing_team, 1) : '-'}</B>{' '}
              of the time. The gap between those and 100% is the point: a great game on the losing side
              exists, and the score is meant to find it.
            </Prose>
            <div className="grid gap-5 md:grid-cols-2">
              {audit.roles.map((role) => (
                <AuditCard key={role.position} role={role} components={score.components} />
              ))}
            </div>
            <Prose>
              Each card shows the win rate by score tenth: a score that means anything climbs from left to
              right, and every role&apos;s does. The second table sets the published weights beside the
              weights a logistic fit of winning on the seven percentiles would choose.
            </Prose>
            <Aside>
              The fitted weights are not adopted, and the reason is the most important sentence on this page.
              Winners take objectives, earn gold and stay alive partly because they are already winning, so a
              fit to wins rewards being on the winning team: it puts kill participation, damage share and
              vision at nothing and objectives, economy and survival at nearly everything. That would make
              the score a second copy of the result. The fit is a check on the hand-set weights, not a
              replacement for them.
            </Aside>
          </>
        )}
      </Section>

      <Section id="limits" title="What it is not">
        <Prose>
          It is not a rating, an MMR or a rank, and Riftline does not turn it into one: Riot&apos;s rank is
          the only ranking here, and it is shown beside the score, never combined with it. It cannot see
          what a player&apos;s team asked of them, so a mid laner who roamed all game to save a losing bot
          lane scores lower than the numbers deserve. It knows nothing about the enemy&apos;s strength: a
          9 against a weak lobby and a 9 against a strong one read the same. And it is one game. Read a
          profile&apos;s average, with its sample, before reading any single score.
        </Prose>
      </Section>
    </>
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
  const lowest = role.deciles[0]
  const highest = role.deciles[role.deciles.length - 1]
  return (
    <div className="frame space-y-3 px-4 py-3">
      <div className="flex items-baseline justify-between">
        <h3 className="display text-base font-600 text-ink">{positionLabel(role.position)}</h3>
        <span className="tnum text-xs text-ink-faint">
          AUC {role.auc !== null ? pct(role.auc) : '-'}, {compact(role.players)} players
        </span>
      </div>
      <div>
        <p className="mb-1 text-xs text-ink-faint">Win rate by score tenth, lowest to highest</p>
        <div
          className="flex h-16 items-end gap-1"
          role="img"
          aria-label={`Win rate by decile: ${role.deciles.map((d) => pct(d.win_rate)).join(', ')}`}
        >
          {role.deciles.map((d, i) => (
            <span
              key={i}
              className="flex-1 rounded-t-sm"
              style={{ height: `${(d.win_rate / peak) * 100}%`, background: 'var(--accent)', opacity: 0.35 + 0.65 * d.win_rate }}
            />
          ))}
        </div>
        {lowest && highest && (
          <p className="tnum mt-1 flex justify-between gap-3 text-[11px] text-ink-faint">
            <span>
              Scores {lowest.low.toFixed(1)} to {lowest.high.toFixed(1)}, {pct(lowest.win_rate)} won
            </span>
            <span className="text-right">
              {highest.low.toFixed(1)} to {highest.high.toFixed(1)}, {pct(highest.win_rate)} won
            </span>
          </p>
        )}
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
