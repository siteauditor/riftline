import type { CSSProperties } from 'react'

import Hint from '../Hint'
import { Stat, StatCell, StatStrip } from '../Stat'
import type { LiveGame, SideRead } from '../../lib/api'
import { tierColor, tierLabel } from '../../lib/format'

/**
 * What the lobby adds up to, above the ten cards that say it in detail.
 *
 * Four figures, each of them a count of measurements rather than a prediction.
 * There is no win probability here and there must not be one: the site holds no
 * model that forecasts a game, and about a third of a lobby hides its identity,
 * which is not a third missing at random. "Three of five lanes have a record
 * and two of them favour your side" is a fact; "62%" would not be.
 *
 * Every cell carries its denominator, because with a 26% lane coverage and four
 * withholding floors a real lobby can leave most of this blank, and a blank
 * that cannot say why it is blank just looks broken.
 */
export default function LobbyBand({
  game,
  you,
}: {
  game: LiveGame
  /** The searched player's puuid, so the comparison has a side to be against. */
  you: string
}) {
  const lobby = game.lobby_rank
  const compare = game.sides
  if (!lobby) return null

  const counted = [
    lobby.hidden > 0 && `${lobby.hidden} hid their identity`,
    lobby.unranked > 0 && `${lobby.unranked} unranked`,
    lobby.unknown > 0 && `${lobby.unknown} could not be looked up`,
    lobby.bots > 0 && `${lobby.bots} bots`,
  ].filter(Boolean) as string[]

  const accent = tierColor(lobby.tier)
  const yourSide = compare?.sides.find((s) => s.team_id === compare.you_team_id)
  const theirSide = compare?.sides.find((s) => s.team_id !== compare.you_team_id)
  const yours = game.participants.find((p) => p.puuid && p.puuid === you)

  return (
    <section style={{ '--accent': accent } as CSSProperties}>
      <StatStrip>
        <StatCell>
          <Stat
            label="Lobby rank"
            value={
              lobby.median_points === null ? (
                <span className="text-ink-faint">Not enough</span>
              ) : (
                tierLabel(lobby.tier, lobby.division)
              )
            }
            color={lobby.median_points === null ? undefined : accent}
            sub={
              lobby.median_points === null
                ? `only ${lobby.ranked} of ten expose a rank`
                : `median of ${lobby.ranked} identified players`
            }
            title={
              'The middle player by rank, not the average: one point separates Diamond I from ' +
              'Master, so a mean over that scale is not a rank anybody holds.' +
              (counted.length ? ` Of the ten, ${counted.join(', ')}.` : '') +
              (lobby.queue_matches_game
                ? ''
                : ' This queue has no rank of its own, so solo queue rank is shown.')
            }
          />
        </StatCell>

        <StatCell>
          <Stat
            label="Against you"
            value={gapValue(theirSide)}
            sub={
              yours?.rank?.tier
                ? `you are ${tierLabel(yours.rank.tier, yours.rank.division)}`
                : 'we could not read your rank in this queue'
            }
            title={gapTitle(theirSide)}
          />
        </StatCell>

        <StatCell>
          <Stat
            label="Lanes ahead"
            value={
              compare && compare.lanes_with_record > 0 ? (
                <>
                  <span style={{ color: 'var(--color-win)' }}>
                    {yourSide?.lanes_favoured ?? compare.sides[0].lanes_favoured}
                  </span>
                  <span className="text-ink-faint"> - </span>
                  <span style={{ color: 'var(--color-loss)' }}>
                    {theirSide?.lanes_favoured ?? compare.sides[1].lanes_favoured}
                  </span>
                </>
              ) : (
                <span className="text-ink-faint">None yet</span>
              )
            }
            sub={
              compare
                ? `${compare.lanes_with_record} of ${compare.lanes_total} lanes have a record`
                : 'lanes are not known in this mode'
            }
            title={
              'Counted only over lanes that have a stored record, and only when the record is big ' +
              'enough to support the claim: a 3-2 over five games is level, not ahead. It ' +
              'describes the champions, not the players.'
            }
          />
        </StatCell>

        <StatCell>
          <Stat
            label="New champions"
            value={
              compare && knownMastery(compare.sides) > 0 ? (
                compare.sides.reduce((n, s) => n + s.off_champion, 0)
              ) : (
                <span className="text-ink-faint">Unknown</span>
              )
            }
            sub={
              compare && knownMastery(compare.sides) > 0
                ? `of ${knownMastery(compare.sides)} players we could check`
                : 'no mastery answers came back'
            }
            title={
              "Players on a champion Riot's own mastery level puts at 3 or below, which is " +
              'roughly ten games. Anyone whose mastery lookup did not finish is counted on ' +
              'neither side of that ratio.'
            }
          />
        </StatCell>
      </StatStrip>

      {compare && (
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-faint">
          {compare.sides.map((side, i) => (
            <span key={side.team_id}>
              <span style={{ color: i === 0 ? 'var(--color-win)' : 'var(--color-loss)' }}>
                {i === 0 ? 'Blue' : 'Red'}
              </span>{' '}
              {sideCounts(side)}
              {side.off_role_known > 0 && side.off_role > 0 && (
                <>
                  {', '}
                  {side.off_role} out of {side.off_role > 1 ? 'their usual roles' : 'their usual role'}
                </>
              )}
            </span>
          ))}
        </p>
      )}

      <SameSidePairs game={game} />
    </section>
  )
}

/**
 * Pairs that keep landing on the same side, as a sentence.
 *
 * Deliberately not a line drawn between two cards: that breaks on every wrap,
 * says nothing to a screen reader, and implies a relationship from three stored
 * games. The wording stays on what we hold, and the hedge is the point: two
 * players in one small ranked pool meet constantly without ever queueing
 * together.
 */
function SameSidePairs({ game }: { game: LiveGame }) {
  // Tolerant of a response without the field: during a deploy the bundle can
  // reach a browser a few seconds before the API that fills it.
  const pairs = game.same_team_pairs ?? []
  if (pairs.length === 0) return null
  const nameOf = (puuid: string) => {
    const player = game.participants.find((p) => p.puuid === puuid)
    return player?.riot_id?.split('#')[0] ?? player?.champion.name ?? 'a player'
  }
  return (
    <p className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-faint">
      {pairs.slice(0, 3).map((pair) => (
        <Hint
          key={`${pair.puuid_a}-${pair.puuid_b}`}
          text={
            `${nameOf(pair.puuid_a)} and ${nameOf(pair.puuid_b)} were on the same side in ` +
            `${pair.games} of the stored games we hold with both of them, winning ${pair.wins}. ` +
            'Riftline only sees the games it has crawled, so this is a pattern rather than a count ' +
            'of how often they play together.'
          }
        >
          <span tabIndex={0}>
            <span className="text-ink-dim">
              {nameOf(pair.puuid_a)} and {nameOf(pair.puuid_b)}
            </span>{' '}
            were on the same side in {pair.games} stored games. Possibly queued together.
          </span>
        </Hint>
      ))}
    </p>
  )
}


function knownMastery(sides: SideRead[]): number {
  return sides.reduce((n, s) => n + s.off_champion_known, 0)
}

function sideCounts(side: SideRead): string {
  const parts = [`${side.ranked} identified`]
  if (side.hidden) parts.push(`${side.hidden} hidden`)
  if (side.unranked) parts.push(`${side.unranked} unranked`)
  if (side.unknown) parts.push(`${side.unknown} could not be looked up`)
  if (side.bots) parts.push(`${side.bots} bots`)
  return parts.join(', ')
}

/**
 * The distance to the other side, in the unit that is actually valid.
 *
 * Tiers everywhere, LP only within one division, and nothing at all when either
 * end is unknown. `numeric_rank` is ordinal with a 100,000 apex stride, so
 * subtracting across Master would tell a Diamond I player they are one point
 * behind.
 */
function gapValue(side: SideRead | undefined) {
  if (!side || side.gap_basis === 'withheld' || side.tier_gap === null) {
    return <span className="text-ink-faint">Not known</span>
  }
  if (side.tier_gap === 0) {
    if (side.points_gap !== null && Math.abs(side.points_gap) >= 100) {
      const divisions = Math.round(side.points_gap / 100)
      return `${Math.abs(divisions)} ${Math.abs(divisions) === 1 ? 'division' : 'divisions'} ${divisions > 0 ? 'above' : 'below'} you`
    }
    return 'About level'
  }
  const tiers = Math.abs(side.tier_gap)
  return `${tiers} ${tiers === 1 ? 'tier' : 'tiers'} ${side.tier_gap > 0 ? 'above' : 'below'} you`
}

function gapTitle(side: SideRead | undefined): string {
  if (!side) return 'There is no second side to compare in this mode.'
  if (side.gap_basis === 'withheld') {
    return (
      "Either your rank or the other side's median is missing, so there is nothing to " +
      'compare. A third of a lobby hides its identity and has no rank to read.'
    )
  }
  if (side.gap_basis === 'tiers_only') {
    return (
      'Counted in tiers rather than LP. Above Diamond the rank scale stops being uniform: one ' +
      'point separates Diamond I from Master, so subtracting LP across that line is not a gap.'
    )
  }
  return "The other side's median rank against yours, in divisions of 100 LP."
}
