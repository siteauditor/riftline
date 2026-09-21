import { Link } from 'react-router-dom'

import PositionIcon from '../PositionIcon'
import RankBadge from '../RankBadge'
import { Loadout, MasteryChip, RoleRecord, SkinArt } from './PlayerBits'
import PlayerRecordChips from './PlayerRecordChips'
import { BLUE, LANES, RED } from './sides'
import type {
  CorpusRecord,
  LiveGame,
  LiveParticipant,
  Position,
  RecordBasis,
} from '../../lib/api'
import { pct, positionLabel } from '../../lib/format'

/**
 * Lane by lane, each blue player facing their red opponent.
 *
 * Only when the server could place all ten players: spectator-v5 carries no
 * positions, so they are inferred, and a lobby with some lanes and some blanks
 * has no layout. Everything else falls back to the team columns.
 */
export default function LaneView({ game, platform, you }: { game: LiveGame; platform: string; you: string }) {
  const at = (team: number, lane: Position) =>
    game.participants.find((p) => p.team_id === team && p.position === lane)
  const confidentAt = game.position_model?.confident_at ?? 0.9

  // Full width, like the rest of the page, with each card pulled in towards the
  // lane icon rather than out to its own edge. Pushed to the edges, the two
  // players in a lane sat a page apart with the icon adrift between them, and
  // nothing on screen said which two were facing each other.
  return (
    <section>
      {/* Side headings belong to the two column layout. Below sm each lane
          stacks, so the sides are labelled on the cards themselves instead. */}
      <div className="mb-1 hidden grid-cols-[1fr_6rem_1fr] items-end gap-3 border-b border-line pb-1.5 sm:grid">
        <h3
          className="display text-right text-base font-600"
          style={{ color: 'var(--color-win)' }}
        >
          Blue side
        </h3>
        <span />
        <h3 className="display text-base font-600" style={{ color: 'var(--color-loss)' }}>
          Red side
        </h3>
      </div>
      <ul>
        {LANES.map((lane) => {
          const blue = at(BLUE, lane)
          const red = at(RED, lane)
          if (!blue || !red) return null
          return (
            // Measured at 390: a three column lane gives each card about
            // 143px, minus a 48px portrait, so roughly 88px of text. That fits
            // one short chip per line and nothing else, which is why the lane
            // stacks here and the centre becomes a divider between the two.
            <li
              key={lane}
              className="grid items-center gap-2 border-b border-line-soft py-2 sm:grid-cols-[1fr_6rem_1fr] sm:gap-3"
            >
              <LaneCard
                p={blue}
                side="blue"
                platform={platform}
                isYou={Boolean(blue.puuid) && blue.puuid === you}
              />
              <LaneCenter
                lane={lane}
                blue={blue}
                red={red}
                confidentAt={confidentAt}
              />
              <LaneCard
                p={red}
                side="red"
                platform={platform}
                isYou={Boolean(red.puuid) && red.puuid === you}
              />
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function LaneCard({
  p,
  side,
  platform,
  isYou,
}: {
  p: LiveParticipant
  side: 'blue' | 'red'
  platform: string
  isYou: boolean
}) {
  const [name, tag] = (p.riot_id ?? '').split('#')
  const linkable = Boolean(p.riot_id && name && tag)
  // Blue is the mirrored side: its art sits on the right, beside the lane icon,
  // so both champions in a lane face each other across it. Only from sm: when
  // the lane stacks, a mirrored card is just a card that reads backwards.
  const mirrored = side === 'blue'

  return (
    // The cell pushes the card towards the lane icon; the card itself is only
    // as wide as its content, so the "you" outline fits the player, not the
    // whole half of the row.
    <div className={`flex min-w-0 ${mirrored ? 'sm:justify-end' : 'justify-start'}`}>
    <div
      // Stacked, the two cards in a lane are one above the other and nothing
      // says which side is which, so on a phone each carries its side's colour
      // as a rule. From sm the columns say it instead.
      style={{ borderLeftColor: mirrored ? 'var(--color-win)' : 'var(--color-loss)' }}
      className={`flex min-w-0 max-w-full items-center gap-2.5 rounded-sm border-l-2 py-1 pl-2 pr-1.5 sm:border-l-0 sm:px-1.5 ${
        mirrored ? 'sm:flex-row-reverse sm:text-right' : ''
      } ${isYou ? 'bg-gold/[0.07] ring-1 ring-gold/40' : ''}`}
    >
      {/* The skin this player is wearing, from spectator's own record of it:
          the same art their teammates see on the loading screen. */}
      <span className="size-12 shrink-0 overflow-hidden rounded-sm bg-raised sm:size-14">
        <SkinArt p={p} className="size-full object-cover" />
      </span>

      <div className="min-w-0 flex-1">
        <p className="display truncate text-[15px] font-600 leading-tight text-ink">
          {p.champion.name}
        </p>
        <p className="truncate text-xs leading-snug">
          {linkable ? (
            <Link
              to={`/summoner/${platform}/${encodeURIComponent(name)}/${encodeURIComponent(tag)}`}
              className="text-ink-dim transition-colors hover:text-gold-bright"
            >
              {name}
            </Link>
          ) : (
            // Never the champion name Riot puts in `riotId` for a hidden player:
            // it would read as a person and link to a profile that does not exist.
            <span className="text-ink-faint">{p.state === 'bot' ? 'Bot' : 'Hidden player'}</span>
          )}
        </p>
        <div
          className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${
            mirrored ? 'sm:justify-end' : ''
          }`}
        >
          <RankBadge
            state={p.state}
            tier={p.rank?.tier}
            division={p.rank?.division}
            leaguePoints={p.rank?.league_points}
          />
          {p.rank && p.rank.games > 0 && (
            <span
              title={`${p.rank.wins}W ${p.rank.losses}L this season, ${pct(p.rank.win_rate, 1)} win rate`}
              className="tnum whitespace-nowrap text-[11px] text-ink-faint"
            >
              {pct(p.rank.win_rate)} WR
            </span>
          )}
          <MasteryChip p={p} />
        </div>
        {/* The player, rather than the champion: everything above this line
            describes the pick or the season, and nothing described them. */}
        <div
          className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${
            mirrored ? 'sm:justify-end' : ''
          }`}
        >
          <PlayerRecordChips p={p} championName={p.champion.name} />
        </div>
        <div
          className={`mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 ${
            mirrored ? 'sm:justify-end' : ''
          }`}
        >
          <Loadout p={p} />
          <RoleRecord p={p} />
        </div>
      </div>
    </div>
    </div>
  )
}

function LaneCenter({
  lane,
  blue,
  red,
  confidentAt,
}: {
  lane: Position
  blue: LiveParticipant
  red: LiveParticipant
  confidentAt: number
}) {
  // Either side's placement can be the close call, and a lane is only as sure
  // as its less certain half.
  const unsure = [blue, red].some(
    (p) => p.position_basis !== 'smite' && (p.position_confidence ?? 1) < confidentAt,
  )
  // Blue's view of the matchup. The two sides' records are mirror images, so
  // one is shown, and the other is only used if blue's is the one missing.
  const record = blue.lane_record ?? mirror(red.lane_record)

  return (
    <div className="flex flex-col items-center justify-center gap-0.5 text-center">
      <PositionIcon position={lane} className="size-5 text-ink-dim" />
      <span className="display text-xs font-600 text-ink-dim">{positionLabel(lane)}</span>
      {unsure && (
        <span
          className="text-[10px] text-gold"
          title="Riot's live data has no positions, so this lane is inferred from the champions and their summoner spells, and this one is a close call. Measured on held-out games, lanes this uncertain are right about half to two thirds of the time."
        >
          likely
        </span>
      )}
      {record ? (
        <span
          className="mt-0.5 w-full"
          style={{ opacity: BASIS_WEIGHT[record.basis] }}
          title={matchupTitle(blue, red, lane, record)}
        >
          {/* Blue's share of the matchup's wins, as blue against red. A weaker
              basis is drawn as a dashed rule rather than a filled bar, so a
              record of two champions who merely shared a game cannot be read
              as a lane record at a glance. */}
          {record.basis === 'team' ? (
            <span className="block border-t border-dashed border-ink-faint" />
          ) : (
            <span className="flex h-1 w-full overflow-hidden rounded-full bg-loss/70">
              <span
                className="h-full bg-win"
                style={{ width: `${Math.round(record.win_rate * 100)}%` }}
              />
            </span>
          )}
          <span className="tnum mt-0.5 block text-[11px] text-ink-dim">
            {record.wins}-{record.games - record.wins}
          </span>
          {BASIS_LABEL[record.basis] && (
            <span className="block text-[10px] leading-tight text-ink-faint">
              {BASIS_LABEL[record.basis]}
            </span>
          )}
          {/* Dropped on a team basis rather than dimmed: a gold lead measured
              against somebody else's laner is not a lead against this one. The
              server drops it too; this is the second lock on the same door. */}
          {record.basis !== 'team' && record.gold_diff_14 != null && (
            <span
              className="tnum block text-[10px]"
              style={{
                color:
                  record.gold_diff_14 >= 0 ? 'var(--color-win)' : 'var(--color-loss)',
              }}
            >
              {signed(Math.round(record.gold_diff_14))}g
            </span>
          )}
        </span>
      ) : (
        // Named rather than left blank. Measured across forty real lobbies,
        // only 26% of lanes have a record on the newest patch, so a silent gap
        // here read as the page having failed to draw something.
        <span
          className="mt-0.5 text-[10px] text-ink-faint"
          title={`We hold fewer than five stored games of ${blue.champion.name} against ${red.champion.name} as ${positionLabel(lane)}, on this patch or the one before it.`}
        >
          no record yet
        </span>
      )}
    </div>
  )
}


// How loudly each step of the fallback ladder is allowed to speak. A pooled
// record is a shade quieter than a current one, and a team scope record is
// quieter again, because the three are not the same claim.
const BASIS_WEIGHT: Record<RecordBasis, number> = {
  role: 1,
  lane: 1,
  lane_pooled: 0.8,
  team: 0.6,
}

const BASIS_LABEL: Record<RecordBasis, string> = {
  role: '',
  lane: '',
  lane_pooled: '2 patches',
  team: 'anywhere on the map',
}

function matchupTitle(
  blue: LiveParticipant,
  red: LiveParticipant,
  lane: Position,
  record: CorpusRecord,
): string {
  const where = record.patches.length > 1 ? `patches ${record.patches.join(' and ')}` : `patch ${record.patches[0] ?? ''}`
  const gold =
    record.gold_diff_14 != null
      ? ` ${blue.champion.name} averages ${signed(Math.round(record.gold_diff_14))} gold at 14 minutes, over ${record.timeline_games} games with timelines.`
      : ''
  if (record.basis === 'team') {
    return (
      `We hold too few lane games of ${blue.champion.name} against ${red.champion.name} as ` +
      `${positionLabel(lane)}, so this counts every stored game with both of them in it, in any ` +
      `lane: ${record.wins} wins and ${record.games - record.wins} losses on ${where}. ` +
      'It is not a lane record.'
    )
  }
  const pooled =
    record.basis === 'lane_pooled'
      ? ' Not enough games on the newest patch alone, so two patches are pooled.'
      : ''
  return (
    `${blue.champion.name} against ${red.champion.name} as ${positionLabel(lane)}: ` +
    `${record.wins} wins and ${record.games - record.wins} losses in our stored games on ${where}.` +
    `${pooled} This is the matchup, not these two players.${gold}`
  )
}

function mirror(r: CorpusRecord | null): CorpusRecord | null {
  if (!r) return null
  return {
    ...r,
    wins: r.games - r.wins,
    win_rate: 1 - r.win_rate,
    gold_diff_14: r.gold_diff_14 == null ? null : -r.gold_diff_14,
  }
}

function signed(n: number): string {
  return n > 0 ? `+${n}` : `${n}`
}
