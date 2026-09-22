import type { MethodReport } from '../../lib/api'
import { pct } from '../../lib/format'
import { Aside, B, Explainer, Prose, Section } from './shared'

export default function LaneLabels() {
  return (
    <Explainer
      slug="lane-labels"
      eyebrow="Lane labels"
      title="Lane labels"
      intro={
        <>
          Every game with a timeline says whether a player won, drew or lost their lane by 14 minutes, in
          five words: won big, won, even, lost, lost big. The label is a measurement against the same role,
          not an opinion, and this page says exactly where the lines are drawn.
        </>
      }
    >
      {(report) => <Body report={report} />}
    </Explainer>
  )
}

function Body({ report }: { report: MethodReport }) {
  const { lanes } = report
  return (
    <>
      <Section id="what" title="What is measured">
        <Prose>
          At 14 minutes, the game&apos;s timeline records every player&apos;s gold, experience and minions
          killed. For each player, Riftline finds their opposite number, the enemy in the same role, and
          computes the player&apos;s share of the pair&apos;s total on those three: gold, experience and CS,
          equally weighted. A share of 0.50 is dead even; 0.54 is the lane shown as &ldquo;54 : 46&rdquo;
          on a match row. Fourteen minutes because that is when plates fall and the first tower usually
          follows, so it is the last moment at which the lane is still mostly a lane.
        </Prose>
        <Prose>
          Junglers are paired with the enemy jungler and supports with the enemy support, on the same
          three numbers. A support&apos;s share moves less than a top laner&apos;s, because supports share
          gold and experience with their carry, and that difference is exactly why the label is placed
          against the same role rather than against a fixed number.
        </Prose>
      </Section>

      <Section id="labels" title="Where the lines are">
        <Prose>
          The question the label answers is not &ldquo;how big was the lead&rdquo; but &ldquo;how unusual
          was it for this role&rdquo;. So the distance from even is placed against every measured lane
          Riftline holds in the same queue and role, as a percentile. The closest{' '}
          <B>{pct(lanes.even_below)}</B> of lanes are even. The widest <B>{pct(1 - lanes.big_from)}</B> are
          won big or lost big. Everything between is won or lost. That split, a third even and a tenth big,
          is the one STRATZ uses for lanes in Dota, where the same question has been asked for years.
        </Prose>
        <Prose>
          On Riftline&apos;s games those lines land about 0.02 and 0.09 from even for most roles: a lane at
          51 : 49 is even, a lane at 56 : 44 is won, and a lane at 60 : 40 is won big. The exact values are
          re-measured with the score every night, so they drift as the corpus grows, and a label given
          last month may sit on the other side of a line today.
        </Prose>
      </Section>

      <Section id="withheld" title="When there is no label">
        <Prose>
          A role with fewer than <B>{lanes.min_games.toLocaleString('en-US')}</B> measured lanes in the
          corpus gets no labels, because a percentile against a handful of games describes the handful. A
          game without a stored timeline has no 14-minute figures and no label; profile games get their
          timeline at the nightly run, or when someone opens the game&apos;s story. A game that ended before
          14 minutes, or where a player had no opposite number in their role, gets none.
        </Prose>
      </Section>

      <Section id="profile" title="On a profile">
        <Prose>
          A profile adds a player&apos;s labels up per role: so many won, so many even, so many lost, with
          the big ones counted separately, over the newest games with a timeline. The bar beside a role is
          those counts in proportion. It answers the question &ldquo;does this player usually win lane&rdquo;
          with a count rather than a feeling, and with the number of games it was counted over.
        </Prose>
      </Section>

      <Section id="limits" title="Where it is wrong">
        <Prose>
          A lane is not always a lane. Roaming mid laners, lane swaps and a jungler camping one side all
          show up as a lane won or lost by a player who was not the reason. A support who roamed to win
          two fights elsewhere reads as behind in their own lane. An early tower dive that cost a death but
          took a plate reads as even. A player who was counter-picked and survived to 49 : 51 did well, and
          the label cannot know it. The label is a fact about the numbers at minute 14, and the death
          review and the win-chance curve are there for the rest of the game.
        </Prose>
        <Aside>
          None of this is hidden in a score. The 14-minute share is printed on every match row beside the
          label, so a reader who disagrees with a label has the number it came from.
        </Aside>
      </Section>
    </>
  )
}
