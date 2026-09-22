import type { ChampionDetail, ChampionProfile, ItemDetail } from './api'
import { pct, positionLabel } from './format'

/**
 * Sentences built from a page's own numbers.
 *
 * A data page is a table to a reader who knows the game and a wall to one
 * who does not; a few sentences that say what the table says fix that for
 * both, and give a crawler text to read. Every sentence here comes from a
 * figure the page already shows, so there is nothing to keep in step and
 * nothing invented: a figure that is withheld leaves its sentence out.
 */

const n = (value: number) => value.toLocaleString('en-US')

export function championSummary(d: ChampionDetail, profile?: ChampionProfile): string[] {
  const o = d.overview
  const name = d.champion.name
  const role = positionLabel(d.position).toLowerCase()
  const out: string[] = []

  const main = d.positions.find((p) => p.position === d.position)
  const others = d.positions
    .filter((p) => p.position !== d.position)
    .slice(0, 2)
    .map((p) => `${positionLabel(p.position).toLowerCase()} in ${pct(p.share)}`)
  const roles =
    main && others.length > 0
      ? ` ${name} is played ${role} in ${pct(main.share)} of games, ${others.join(' and ')}.`
      : ''

  out.push(
    `On patch ${d.patch}, ${name} won ${pct(o.win_rate, 1)} of ${n(o.games)} ranked solo games as ${role} ` +
      `in the games Riftline holds, a rate the sample supports down to ${pct(o.confidence_win_rate, 1)}. ` +
      `${name} was picked in ${pct(o.pick_rate, 1)} of games and banned in ${pct(o.ban_rate, 1)}.` +
      roles,
  )

  if (o.tier) {
    out.push(
      `That places ${name} in tier ${o.tier} among ${role} champions on this patch, ranked by that lower ` +
        `figure rather than the raw win rate, so a champion with few games does not outrank one with many.`,
    )
  }

  const previous = o.previous
  if (previous && previous.win_rate_moved) {
    const up = o.win_rate > previous.win_rate
    out.push(
      `Against patch ${previous.patch}, ${name}'s win rate ${up ? 'rose' : 'fell'} from ${pct(previous.win_rate, 1)} ` +
        `to ${pct(o.win_rate, 1)}, a change the samples support.`,
    )
  }

  out.push(
    `A typical game as ${role} ends ${o.avg_kills.toFixed(1)} / ${o.avg_deaths.toFixed(1)} / ${o.avg_assists.toFixed(1)} ` +
      `with ${o.avg_cs_per_min.toFixed(1)} CS a minute and ${n(Math.round(o.avg_damage))} damage to champions.`,
  )

  if (profile?.blurb) out.push(profile.blurb)
  return out
}

export function itemSummary(item: ItemDetail): string[] {
  const f = item.figures
  if (!f) return []
  const out: string[] = []
  if (f.buyers === 0) {
    out.push(`Nobody bought ${item.name} in the ${n(f.ordered_players)} games with a timeline on patch ${f.patch}.`)
    return out
  }
  const when =
    f.minute_p50 !== null ? `, usually by minute ${Math.round(f.minute_p50)}` : ''
  out.push(
    `On patch ${f.patch}, ${item.name} was bought by ${pct(f.bought_share, 1)} of the ${n(f.ordered_players)} ` +
      `players with a timeline${when}, and ${pct(f.held_share, 1)} of players still held it when the game ended.`,
  )
  if (item.group === 'finished') {
    if (f.delta === null) {
      out.push(
        `Too few purchases to compare it with the other items in its slot: that comparison needs ${n(f.slot_min_games)}.`,
      )
    } else {
      const sign = f.delta >= 0 ? 'higher' : 'lower'
      out.push(
        `Bought in the same slot as the alternatives, it left the buyer's win rate ${Math.abs(f.delta * 100).toFixed(1)} points ` +
          `${sign} over ${n(f.delta_games)} purchases, which is the figure to read: a raw buyer win rate mostly ` +
          `measures how late an item is bought.`,
      )
    }
  }
  if (f.champions.length > 0) {
    const top = f.champions.slice(0, 3).map((c) => c.champion.name)
    out.push(`It is built most by ${top.join(', ')}.`)
  }
  return out
}
