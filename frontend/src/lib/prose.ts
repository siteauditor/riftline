import type { Analytics, ChampionDetail, ItemDetail, Profile } from './api'
import { pct, positionLabel, tierLabel } from './format'

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

export function championSummary(d: ChampionDetail): string[] {
  const o = d.overview
  const name = d.champion.name
  const role = positionLabel(d.position).toLowerCase()
  const queue = d.queue_id === 440 ? 'ranked flex' : 'ranked solo'
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

  // The first sentence stands alone: a phone shows only it until asked.
  out.push(
    `On patch ${d.patch}, ${name} won ${pct(o.win_rate, 1)} of ${n(o.games)} ${queue} games as ${role} ` +
      `in the games Riftline holds, a rate the sample supports down to ${pct(o.confidence_win_rate, 1)}.`,
  )
  out.push(`${name} was picked in ${pct(o.pick_rate, 1)} of games and banned in ${pct(o.ban_rate, 1)}.${roles}`)

  if (o.tier) {
    out.push(
      `That places ${name} in tier ${o.tier} among ${role} champions on this patch: a place in a ranking by ` +
        `that lower figure rather than the raw win rate, not a measured gap, so a few games can move it.`,
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

  // Not the lore blurb: Riot cuts it off mid-sentence ("Once a powerful yet
  // wayward..."), and the Story tab has the whole of it.
  return out
}

/**
 * Why the slice on screen is not the one the link asked for, when the API
 * served another: a patch it does not hold, or a role the champion was not
 * played in there. Empty when the page is what was asked for.
 */
export function fallbackLines(d: ChampionDetail, name: string): string[] {
  const lines: string[] = []
  if (d.requested_patch) {
    lines.push(`Riftline holds no games of ${name} on patch ${d.requested_patch}, so this is patch ${d.patch}.`)
  }
  if (d.requested_position) {
    const served = d.positions.find((p) => p.position === d.position)
    lines.push(
      `${name} has no ${positionLabel(d.requested_position).toLowerCase()} games on patch ${d.patch}. ` +
        `This is ${positionLabel(d.position).toLowerCase()}, where ${pct(served?.share ?? 0)} of ${name}'s games are.`,
    )
  }
  return lines
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

/**
 * A player in sentences: rank and record, then what the stored games say.
 * The first sentence stands alone as the page's description. A role's score
 * is mentioned only when the profile has enough scored games to offer it,
 * the same floor the strengths panel applies.
 */
export function profileSummary(profile: Profile, analytics?: Analytics): string[] {
  const id = profile.riot_id
  const region = profile.platform_label
  const out: string[] = []

  const solo = profile.ranks.find((r) => r.queue === 'RANKED_SOLO_5x5' && r.tier)
  if (solo) {
    out.push(
      `${id} is ${tierLabel(solo.tier, solo.division)} with ${n(solo.league_points)} LP in ranked solo on ${region}, ` +
        `${n(solo.wins)} wins and ${n(solo.losses)} losses this season (${pct(solo.win_rate)}).`,
    )
  } else {
    out.push(`${id} plays on ${region} and has no ranked solo placement this season.`)
  }

  if (!analytics || analytics.games_analysed === 0) return out
  const games = analytics.games_analysed
  const role = analytics.roles[0]
  const t = analytics.totals
  out.push(
    `Over the ${n(games)} ${games === 1 ? 'game' : 'games'} Riftline holds, ${profile.game_name ?? id} ` +
      (role ? `plays ${positionLabel(role.position).toLowerCase()} in ${pct(role.share)} of games and ` : '') +
      `wins ${pct(t.win_rate)}, at a ${t.kda.toFixed(2)} KDA and ${t.cs_per_min.toFixed(1)} CS a minute.`,
  )

  const scored = role && analytics.score_profile.find((p) => p.position === role.position && p.enough)
  if (scored) {
    out.push(
      `As ${positionLabel(scored.position).toLowerCase()}, their Riftline score averages ` +
        `${scored.avg_score.toFixed(1)} over ${n(scored.scored_games)} scored games, ` +
        `an average placement of ${scored.avg_placement.toFixed(1)} of 10 in the lobby` +
        (scored.mvp ? `, with ${n(scored.mvp)} MVP ${scored.mvp === 1 ? 'game' : 'games'}` : '') +
        '.',
    )
  }

  const top = analytics.champions[0]
  if (top && top.games >= 3) {
    out.push(
      `Their most played champion is ${top.champion.name}: ${n(top.games)} games at ${pct(top.win_rate)}.`,
    )
  }
  return out
}
