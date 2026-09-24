import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

import Hint from '../Hint'
import LobbyRanks from '../LobbyRanks'
import { EmptyState } from '../StateViews'
import WinRateRange from '../WinRateRange'
import type { DraftEvidence, DraftResponse, DraftSuggestion } from '../../lib/api'
import { COMFORT_LEVELS } from '../../lib/draftBoard'
import { DAMAGE_TEXT, mainType } from '../../lib/damage'
import { compact, pct, positionLabel } from '../../lib/format'
import { lowerFloor } from '../../lib/minGames'
import { championPath } from '../../lib/searchParams'

/**
 * The answer half of the draft page: the ranked picks, who to ban, and how the
 * ranking works. It reads only the response and the two settings it explains.
 */

export function SuggestionSkeleton() {
  return (
    <ul className="space-y-1.5" aria-hidden>
      {Array.from({ length: 8 }).map((_, i) => (
        <li key={i} className="flex items-center gap-3 border-b border-line-soft px-3 py-2.5">
          <span className="skeleton size-10 shrink-0" />
          <span className="flex-1 space-y-1.5">
            <span className="skeleton block h-4 w-32" />
            <span className="skeleton block h-3 w-52 max-w-full" />
          </span>
          <span className="skeleton h-7 w-14" />
        </li>
      ))}
    </ul>
  )
}

/** What the results line says about mastery: only what actually happened. */
function masteryNote(data: DraftResponse, comfort: number): string {
  if (comfort <= 0) return 'mastery off'
  switch (data.personalisation.status) {
    case 'used':
      return 'weighted by your mastery'
    case 'stale':
      return 'weighted by your stored mastery'
    default:
      return 'not personalised'
  }
}

/**
 * No champion clears the floor: an answer, with the way out. The API used to
 * 404 here with "Ingest more matches or lower min_games", which the page showed
 * as "Something went wrong".
 */
function TooFewGames({
  data,
  min,
  onMinGames,
}: {
  data: DraftResponse
  min: number
  onMinGames: (min: number) => void
}) {
  // The highest offered floor that still shows something, else the most any
  // champion has.
  const lower = lowerFloor(data.most_games, min)
  let action: ReactNode = null
  if (lower !== null) {
    action = (
      <Button variant="outline" size="sm" onClick={() => onMinGames(lower)}>
        Lower the minimum to {lower} games
      </Button>
    )
  }
  return (
    <EmptyState
      title={`No ${positionLabel(data.position).toLowerCase()} champion has ${min}+ games`}
      body={
        data.most_games > 0
          ? `On patch ${data.patch} the most games any ${positionLabel(data.position).toLowerCase()} champion has is ${data.most_games}.`
          : `Riftline holds no ${positionLabel(data.position).toLowerCase()} games on patch ${data.patch} yet.`
      }
      action={action}
    />
  )
}

export function Results({
  data,
  comfort,
  min,
  stale,
  onMinGames,
  onUncheck,
  checker,
}: {
  data: DraftResponse
  comfort: number
  min: number
  stale: boolean
  onMinGames: (min: number) => void
  onUncheck: (id: number) => void
  /** The "check a champion" field, drawn under the list. */
  checker?: ReactNode
}) {
  if (data.suggestions.length === 0 && data.pinned.length === 0) {
    return <TooFewGames data={data} min={min} onMinGames={onMinGames} />
  }
  const earlier = data.patches.filter((p) => p !== data.patch)
  // In solo queue every ban comes before any pick, so while nothing is picked
  // the question on screen is who to ban.
  const banPhase = data.allies.length + data.enemies.length === 0
  return (
    <div aria-busy={stale} className={stale ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p role="status" className="flex flex-wrap items-baseline gap-x-3 text-xs text-ink-faint">
          <span>
            Patch {data.patch}
            {earlier.length > 0 && `, lane records with ${earlier.join(' and ')}`}
          </span>
          <span>{positionLabel(data.position)}</span>
          {data.lane_opponent && (
            <span>
              against {data.lane_opponent.champion.name}
              {data.lane_opponent.source === 'inferred' && ` (${pct(data.lane_opponent.probability, 0)} likely)`}
            </span>
          )}
          {data.blind && <span>blind pick</span>}
          <span>{masteryNote(data, comfort)}</span>
        </p>
        <Hint
          text={
            'The figure is the pick’s win rate on this board: its own rate in this role, moved by ' +
            'its record against your lane opponent. The bar is the range its sample supports, and ' +
            'the list is ranked by the left end of that bar, plus comfort, so a few lucky games ' +
            'cannot top it.'
          }
        >
          <button
            type="button"
            className="rounded-sm text-[11px] text-ink-faint underline decoration-line underline-offset-2 outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            Reading a row
          </button>
        </Hint>
      </div>
      {banPhase && (
        <div className="mt-4">
          <Bans data={data} />
        </div>
      )}

      {data.pinned.length > 0 && (
        <section aria-label="Champions you checked" className="mt-4">
          <h2 className="eyebrow">Checked</h2>
          <ul className="mt-1">
            {data.pinned.map((s) => (
              <SuggestionRow
                key={`pinned-${s.champion.id}`}
                suggestion={s}
                data={data}
                place={
                  s.below_min
                    ? `under ${min} games`
                    : s.rank
                      ? `#${s.rank}`
                      : ''
                }
                onUncheck={() => onUncheck(s.champion.id)}
              />
            ))}
          </ul>
        </section>
      )}

      <ol className="mt-3">
        {data.suggestions.map((s, i) => (
          <SuggestionRow key={s.champion.id} suggestion={s} place={String(i + 1)} data={data} />
        ))}
      </ol>

      {/* Under the list, not over it: on a phone the board and these two
          pushed the first suggestion to 912 px of an 844 px screen. */}
      {checker && <div className="mt-4 max-w-xs">{checker}</div>}
      {data.lobby_ranks && <LobbyRanks lobby={data.lobby_ranks} className="mt-4" />}

      {/* items-start: the folded "How this is ranked" box stretched to the ban
          list's height and sat there as a large empty frame. */}
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-2">
        {!banPhase && <Bans data={data} />}
        <HowScored data={data} comfort={comfort} />
      </div>
    </div>
  )
}

const CALL_WORDS: Record<DraftEvidence['call'], string> = {
  favoured: 'favoured',
  unfavoured: 'unfavoured',
  level: 'too few games to call',
}

const points = (value: number) => `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)} points`
const record = (e: DraftEvidence) => `${e.wins}-${e.games - e.wins} over ${e.games} games`

/** One record against the rest of the board, in a line. */
function recordLine(e: DraftEvidence, where: string, note = ''): string {
  return (
    `${where} ${e.champion.name}${note}: ${e.wins}-${e.games - e.wins} (${pct(e.win_rate, 0)}) ` +
    `against its usual ${pct(e.own_rate, 0)}, ${CALL_WORDS[e.call]}`
  )
}

/**
 * The lane lines, written here because they name the opponent. A marked laner's
 * record counts in full; an inferred one's counts in proportion to how likely
 * that enemy is to be in your lane, and the line says both.
 */
function laneLines(s: DraftSuggestion, data: DraftResponse): string[] {
  const lanes = s.evidence.filter((e) => e.kind === 'lane')
  const lines: string[] = []
  for (const e of lanes) {
    if (data.lane_opponent?.source === 'marked') {
      lines.push(
        e.call === 'level'
          ? `against ${e.champion.name}: ${record(e)}, too few games to call, ${points(e.lift)}`
          : `${e.call} into ${e.champion.name}: ${record(e)}, ${points(e.lift)}`,
      )
    } else {
      lines.push(
        `${e.champion.name} in your lane (${pct(e.weight, 0)} likely): ${record(e)}, ` +
          `${CALL_WORDS[e.call]}, counts ${points(e.weight * e.lift)}`,
      )
    }
    if (e.gold_diff_14 !== null) {
      lines.push(
        `usually ${e.gold_diff_14 >= 0 ? '+' : ''}${Math.round(e.gold_diff_14).toLocaleString('en-US')} gold ` +
          `by 14 against ${e.champion.name}, over ${e.timeline_games} games with timelines`,
      )
    }
  }
  if (data.blind) {
    for (const e of s.blind_risks) {
      lines.push(
        `blind risk: loses to ${e.champion.name}, ${e.wins}-${e.games - e.wins} over ${e.games} games, ` +
          `picked in ${pct(e.weight, 0)} of ${positionLabel(data.position).toLowerCase()} games`,
      )
    }
  }
  if (s.laning) {
    const bits = [
      s.laning.gold_diff_14 !== null &&
        `${s.laning.gold_diff_14 >= 0 ? '+' : ''}${Math.round(s.laning.gold_diff_14).toLocaleString('en-US')} gold`,
      s.laning.cs_diff_14 !== null && `${s.laning.cs_diff_14 >= 0 ? '+' : ''}${s.laning.cs_diff_14.toFixed(1)} CS`,
    ].filter(Boolean)
    if (bits.length) {
      lines.push(`laning at 14 minutes: ${bits.join(' and ')}, over ${s.laning.timeline_games} games with timelines`)
    }
  }
  return lines
}

/**
 * A pick that pulls a one-sided team back toward even, said with the figures:
 * the team's share of its main type now, and with this pick. Only when the API
 * marks it: your side leans one way and this pick deals mostly another.
 */
function DamageNote({ s, data }: { s: DraftSuggestion; data: DraftResponse }) {
  const damage = s.damage
  const allies = data.team_damage.allies?.shares
  if (!damage?.balances || !damage.team_after || !allies) return null
  const kind = mainType(damage.own)
  const leaning = damage.balances
  return (
    <>
      <span className={DAMAGE_TEXT[kind]}>brings {kind} damage</span>: your team is {pct(allies[leaning], 0)}{' '}
      {leaning}, {pct(damage.team_after[leaning], 0)} with {s.champion.name}
    </>
  )
}

function SuggestionRow({
  suggestion: s,
  place,
  data,
  onUncheck,
}: {
  suggestion: DraftSuggestion
  place: string
  data: DraftResponse
  onUncheck?: () => void
}) {
  const others = s.evidence.filter((e) => e.kind !== 'lane')
  const slug = s.champion.slug
  const opponent = data.lane_opponent?.champion
  const build = slug ? championPath(slug, data.position) : null
  // The counters tab, filtered to the opponent: that matchup's own page.
  const counters =
    build && opponent ? `${build}?${new URLSearchParams({ tab: 'counters', q: opponent.name })}` : null
  const duoRole = data.position === 'BOTTOM' ? 'support' : 'ADC'
  const lines = [...laneLines(s, data), ...s.reasons]
  const balances = Boolean(s.damage?.balances && data.team_damage.allies?.shares)

  return (
    <li className="border-b border-line-soft px-1 py-2.5">
      <div className="flex items-start gap-3">
        <span className="tnum w-12 shrink-0 pt-1 text-xs text-ink-faint">{place}</span>
        {s.champion.icon_url && (
          <img src={s.champion.icon_url} alt="" className="size-10 shrink-0 rounded-sm" loading="lazy" decoding="async" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
            {build ? (
              <Link
                to={build}
                viewTransition
                className="font-display text-sm font-700 text-ink underline decoration-transparent underline-offset-2 transition-colors hover:text-gold-bright hover:decoration-gold-bright"
              >
                {s.champion.name}
              </Link>
            ) : (
              <span className="font-display text-sm font-700 text-ink">{s.champion.name}</span>
            )}
            {s.comfort_bonus >= 0.0005 && (
              <span className="tnum text-[11px] text-accent-bright">
                +{(s.comfort_bonus * 100).toFixed(1)} comfort
              </span>
            )}
            {counters && (
              <Link
                to={counters}
                viewTransition
                className="text-[11px] text-ink-faint underline decoration-line underline-offset-2 hover:text-ink"
              >
                vs {opponent?.name}
              </Link>
            )}
            {onUncheck && (
              <button
                type="button"
                onClick={onUncheck}
                aria-label={`Stop checking ${s.champion.name}`}
                className="rounded-sm text-[11px] text-ink-faint underline decoration-line underline-offset-2 outline-none hover:text-loss focus-visible:ring-2 focus-visible:ring-accent/60"
              >
                remove
              </button>
            )}
          </div>
          {(lines.length > 0 || balances) && (
            <ul className="mt-0.5 text-xs leading-relaxed text-ink-dim">
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
              {balances && (
                <li>
                  <DamageNote s={s} data={data} />
                </li>
              )}
            </ul>
          )}
          {others.length > 0 && (
            <details className="mt-1 text-[11px] text-ink-faint">
              <summary className="cursor-pointer select-none hover:text-ink-dim">
                {others.length} {others.length === 1 ? 'record' : 'records'} with the rest of the
                board, shown, not scored
              </summary>
              <ul className="mt-1 space-y-0.5 pl-3">
                {others.map((e) => (
                  <li key={`${e.kind}-${e.champion.id}`}>
                    {recordLine(
                      e,
                      e.kind === 'enemy' ? 'against' : 'beside',
                      e.kind === 'enemy' && data.duo?.id === e.champion.id ? ` (their ${duoRole})` : '',
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <div className="shrink-0 text-right">
          <WinRateRange
            rate={s.expected}
            low={s.range_low}
            high={s.range_high}
            description={
              `${pct(s.expected, 1)} on this board, a range of ${pct(s.range_low, 1)} to ` +
              `${pct(s.range_high, 1)} over ${s.games} games`
            }
          />
          <p className="tnum mt-1 text-[11px] text-ink-faint">{compact(s.games)} games</p>
        </div>
      </div>
    </li>
  )
}

function Bans({ data }: { data: DraftResponse }) {
  if (data.ban_candidates.length === 0) return null
  return (
    <section>
      <h2 className="eyebrow">Worth banning</h2>
      <p className="mt-0.5 text-[11px] leading-relaxed text-ink-faint">
        {data.allies.length > 0
          ? 'The patch’s strongest picks. Each one’s record against the champions your team has locked in is listed with it, not scored.'
          : data.enemies.length > 0
            ? 'None of your team is locked in yet, so these are simply the patch’s strongest picks.'
            : 'Nothing is locked in yet, so these are simply the patch’s strongest picks.'}
      </p>
      <ol className="mt-2">
        {data.ban_candidates.map((c) => (
          <li key={c.champion.id} className="flex items-start gap-2.5 border-b border-line-soft py-2">
            {c.champion.icon_url && (
              <img src={c.champion.icon_url} alt="" className="size-8 rounded-sm" loading="lazy" decoding="async" />
            )}
            <div className="min-w-0 flex-1">
              <p className="font-display text-sm font-600 text-ink">
                {c.champion.name}
                <span className="ml-1.5 text-[11px] text-ink-faint">{positionLabel(c.position)}</span>
              </p>
              <ul className="text-[11px] leading-snug text-ink-faint">
                {c.evidence.map((e) => (
                  <li key={e.champion.id}>{recordLine(e, 'against')}</li>
                ))}
              </ul>
            </div>
            <WinRateRange
              rate={c.win_rate}
              low={c.range_low}
              high={c.range_high}
              size="sm"
              description={`${pct(c.win_rate, 1)} over ${c.games} games, a range of ${pct(c.range_low, 1)} to ${pct(c.range_high, 1)}`}
            />
          </li>
        ))}
      </ol>
    </section>
  )
}

function HowScored({ data, comfort }: { data: DraftResponse; comfort: number }) {
  const m = data.model
  // The bonus scales with the weight, so the largest gain is at the largest
  // weight the page offers, not at a weight of 1. The text said 10 points "at
  // the strongest setting", where the strongest setting gives 4.
  const strongest = COMFORT_LEVELS[COMFORT_LEVELS.length - 1]
  const level = COMFORT_LEVELS.find((c) => c.value === comfort) ?? COMFORT_LEVELS[0]
  const points = (weight: number) => (weight * m.comfort_max_bonus * 100).toFixed(1)
  const earlier = data.patches.filter((p) => p !== data.patch)
  return (
    <details className="frame px-4 py-3 text-xs leading-relaxed text-ink-dim">
      <summary className="cursor-pointer text-ink">How this is ranked</summary>
      <p className="mt-2">
        Every champion starts from its own win rate in this role on patch {data.patch}, shown as the
        range its sample supports, and the list is ranked by the low end of that range, as the tier
        list is, so a few lucky games cannot top it.
      </p>
      <p className="mt-2">
        The record against your lane opponent moves a pick toward what it shows, by{' '}
        <span className="tnum text-ink">games / (games + {m.lane_strength})</span> of the distance
        from the champion’s own rate: a lane record counts for half at{' '}
        <span className="tnum text-ink">{m.lane_strength}</span> games. Wins and losses count the
        same, and a lane is called favoured only when the record makes that 90% likely.
        {earlier.length > 0 &&
          ` Records include patch ${earlier.join(' and ')}, each read against the champion’s rate on that patch.`}{' '}
        The board cannot move a pick more than{' '}
        <span className="tnum text-ink">{(m.context_lift_cap * 100).toFixed(0)} points</span>.
      </p>
      <p className="mt-2">
        Records against the other enemies and beside your allies are listed but not scored: measured
        on these games, they repeat from one patch to the next no more than chance does. They will
        count once they do.
      </p>
      <p className="mt-2">
        The damage bar under each team adds up each champion’s usual damage by type, from{' '}
        <span className="tnum text-ink">{data.team_damage.min_games}</span> games (in its role when it
        has them there), and calls a side one-sided at{' '}
        <span className="tnum text-ink">{pct(data.team_damage.one_sided_share, 0)}</span> of one type.
        It is shown, not scored: too few one-sided teams have been measured to say what it costs.
      </p>
      <p className="mt-2">
        Mastery is a preference, not evidence: a fully mastered champion gains up to{' '}
        <span className="tnum text-ink">{points(strongest.value)} points</span> at {strongest.label},
        less the longer ago you last played it (half at six months, a quarter after a year). The
        weight is now {level.label}
        {level.value > 0 && (
          <>
            , worth up to <span className="tnum text-ink">{points(level.value)} points</span>
          </>
        )}
        .
      </p>
    </details>
  )
}
