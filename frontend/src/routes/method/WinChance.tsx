import type { MethodReport, WinModelMethod } from '../../lib/api'
import { compact, pct } from '../../lib/format'
import { Aside, B, Explainer, Prose, Section } from './shared'

export default function WinChance() {
  return (
    <Explainer
      slug="win-chance"
      eyebrow="The win chance"
      title="The win chance"
      intro={
        <>
          A game&apos;s story opens with each side&apos;s chance to win, minute by minute, and the three
          moments that decided it. The curve comes from a model fitted on Riftline&apos;s own games every
          night and graded on games it had not seen. Here is what it reads, how well it does, and what it
          cannot see.
        </>
      }
    >
      {(report) => <Body report={report} />}
    </Explainer>
  )
}

function Body({ report }: { report: MethodReport }) {
  const model = report.win_model
  return (
    <>
      <Section id="what" title="What the curve shows">
        <Prose>
          At each minute of a game, the model looks at the state of the map and says how often, in the
          games Riftline holds, the blue side went on to win from a state like that. A curve at 50% is an
          even game; 80% at minute 25 means that, of stored games in a state like this one at minute 25,
          about four in five ended in a blue win. Red&apos;s chance is one minus blue&apos;s. When a page
          is about one player, the curve is drawn from their side.
        </Prose>
        <Prose>
          It is a description of similar games, not a prophecy about this one. A team at 90% still loses
          one game in ten, and those games are the ones people remember.
        </Prose>
      </Section>

      <Section id="how" title="How it is made">
        <Prose>
          The model is a logistic regression on the game state, blue minus red: gold, kills, towers,
          inhibitors down, dragons, the dragon soul, the Elder and Baron buffs, Voidgrubs, the Rift Herald,
          Atakhan and champion levels. Every feature has one weight at minute 0 and another at minute 40,
          and the effect moves in a straight line between them. That is how a gold lead can matter
          differently at 8 minutes and at 35 without the model jumping at a boundary between game phases,
          which a set of phase models would do.
        </Prose>
        <Prose>
          One rule is imposed on the fit: no feature may count against the side that holds it. Fitted
          freely, the model read a tower at 10 minutes as minus 2.9 points and a Baron buff at 20 as
          minus 4.1, because early towers and Barons correlate with things the model was already crediting
          through gold. Harmless to the curve, absurd as the effect of an event, and the moments below are
          built from those effects, so the constraint stays.
        </Prose>
        {model ? (
          <Prose>
            It is trained on <B>{compact(model.trained_games)}</B> ranked solo games (
            {compact(model.trained_rows)} game-minutes), refitted every night as the corpus grows, and
            shown on ranked solo and ranked flex games. It is not shown on ARAM or Arena, whose maps it has
            never seen.
          </Prose>
        ) : (
          <Prose>The model has not been trained yet; it is fitted every night from the stored games.</Prose>
        )}
      </Section>

      <Section id="grade" title="How well it does">
        <Prose>
          A model graded on the games it was fitted to would look better than it is. So it is graded on
          five folds, each held out in turn, split by game and never by minute, because the minutes of one
          game are near copies of each other and splitting them would let the model see the answer.
        </Prose>
        {model?.cv.overall ? (
          <Grades model={model} />
        ) : (
          <Prose>The grades appear once the model has been fitted.</Prose>
        )}
        {model && !model.published && (
          <Aside>Withheld from game pages right now: {model.withheld}.</Aside>
        )}
        {model && (
          <Prose>
            Game pages show the curve only while it removes at least{' '}
            <B>{((model.gate.min_skill ?? 0) * 100).toFixed(0)}%</B> of the error of always guessing
            blue&apos;s win rate and its calibration error stays under{' '}
            <B>{((model.gate.max_ece ?? 0) * 100).toFixed(0)} points</B>. Below that the curve is withheld,
            the way a thin sample is withheld everywhere else on the site.
          </Prose>
        )}
      </Section>

      {model && model.effects.length > 0 && <Effects model={model} />}

      <Section id="moments" title="The moments that decided it">
        <Prose>
          Events closer together than 15 seconds are one sequence: a fight, and the objective taken off
          it. A sequence is measured on the curve itself, from just before its first event to a minute
          after its last, and the three biggest swings are the moments a game page lists. Each is described
          from its events: &ldquo;Red won a fight 4 for 1 and took Baron, minus 35.8&rdquo;.
        </Prose>
        <Prose>
          Measuring on the curve rather than adding up each event&apos;s own effect was a correction. The
          model credits a Baron mostly through the gold and towers that follow it, so a Baron buff alone is
          worth a point or three, and the sum of a fight&apos;s events made the fights that decided games
          look small. A minute of curve after the fight contains what the fight bought.
        </Prose>
      </Section>

      <Section id="limits" title="What it cannot see">
        <Prose>
          Items, champions, who is dead and for how long, where anyone stands, summoner spells and
          respawn timers. A 4-for-0 fight with Baron up reads the same as one with Baron down. A team that
          is behind on the board but ahead in scaling reads as behind. It also reads only what the
          timeline records once a minute, so a lead that appeared and vanished inside a minute is never
          seen. These are the reasons a moment on the curve should be read as &ldquo;this is when the
          numbers turned&rdquo; rather than &ldquo;this is why&rdquo;.
        </Prose>
        <Prose>
          A game&apos;s timeline is fetched when someone first opens its story, one Riot call, once. It never
          takes the last calls the key keeps for player searches, so on a busy key the section says so and
          offers to try again.
        </Prose>
      </Section>
    </>
  )
}

function Grades({ model }: { model: WinModelMethod }) {
  const overall = model.cv.overall!
  return (
    <>
      <Prose>
        Held out, it called the winner <B>{pct(overall.accuracy, 1)}</B> of the time across every minute
        of every game. Its Brier score, the average squared error of the probability it gave, is{' '}
        <B>{overall.brier.toFixed(3)}</B> against {overall.baseline_brier.toFixed(3)} for always guessing
        blue&apos;s overall win rate, so it removes <B>{pct(overall.skill, 1)}</B> of that guess&apos;s
        error. Its calibration error is <B>{((model.cv.ece ?? 0) * 100).toFixed(1)} points</B>: when it
        says 70%, the side wins about 70% of the time, and the second table shows that at every level.
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
      <Prose>
        The first ten minutes are the hardest to call, and honestly so: little has happened, and the model
        says close to 50% because that is the truth of the state. From 20 minutes on, most games have
        turned, and the model is right most of the time because the board is.
      </Prose>
    </>
  )
}

function Effects({ model }: { model: WinModelMethod }) {
  return (
    <Section id="effects" title="What one more of each is worth">
      <Prose>
        From an even game, in points of win chance. These are the model&apos;s own weights at three
        moments of the game, and they are why the moments above are measured on the curve rather than
        from this table: the gold that follows a Baron is worth far more than the buff.
      </Prose>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[480px] border-collapse text-sm">
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
    </Section>
  )
}
