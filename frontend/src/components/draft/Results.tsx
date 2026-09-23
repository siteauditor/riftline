import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/button'

import Hint from '../Hint'
import { EmptyState } from '../StateViews'
import WinRateRange from '../WinRateRange'
import type { DraftEvidence, DraftResponse, DraftSuggestion } from '../../lib/api'
import { COMFORT_LEVELS, MIN_GAMES_PRESETS } from '../../lib/draftBoard'
import { compact, pct, positionLabel } from '../../lib/format'

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
  const lower =
    [...MIN_GAMES_PRESETS].reverse().find((v) => v <= data.most_games && v < min) ??
    (data.most_games > 0 && data.most_games < min ? data.most_games : null)
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
}: {
  data: DraftResponse
  comfort: number
  min: number
  stale: boolean
  onMinGames: (min: number) => void
}) {
  if (data.suggestions.length === 0) {
    return <TooFewGames data={data} min={min} onMinGames={onMinGames} />
  }
  const earlier = data.patches.filter((p) => p !== data.patch)
  return (
    <div aria-busy={stale} className={stale ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p role="status" className="flex flex-wrap items-baseline gap-x-3 text-xs text-ink-faint">
          <span>
            Patch {data.patch}
            {earlier.length > 0 && `, lane records with ${earlier.join(' and ')}`}
          </span>
          <span>{positionLabel(data.position)}</span>
          {data.enemy_laner && <span>against {data.enemy_laner.name}</span>}
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

      <ol className="mt-3">
        {data.suggestions.map((s, i) => (
          <SuggestionRow key={s.champion.id} suggestion={s} place={i + 1} data={data} />
        ))}
      </ol>

      {/* items-start: the folded "How this is scored" box stretched to the ban
          list's height and sat there as a large empty frame. */}
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-2">
        <Bans data={data} />
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

/** One record, in a line: the other champion, the W-L, and against what. */
function recordLine(e: DraftEvidence, where: string): string {
  return (
    `${where} ${e.champion.name}: ${e.wins}-${e.games - e.wins} (${pct(e.win_rate, 0)}) ` +
    `against its usual ${pct(e.own_rate, 0)}, ${CALL_WORDS[e.call]}`
  )
}

function SuggestionRow({
  suggestion: s,
  place,
  data,
}: {
  suggestion: DraftSuggestion
  place: number
  data: DraftResponse
}) {
  const others = s.evidence.filter((e) => e.kind !== 'lane')
  const slug = s.champion.slug
  const build = slug ? `/champions/${slug}?position=${data.position}` : null
  // The counters tab, filtered to the opponent: that matchup's own page.
  const counters =
    slug && data.enemy_laner
      ? `/champions/${slug}?${new URLSearchParams({
          position: data.position,
          tab: 'counters',
          q: data.enemy_laner.name,
        })}`
      : null

  return (
    <li className="border-b border-line-soft px-1 py-2.5">
      <div className="flex items-start gap-3">
        <span className="tnum w-5 shrink-0 pt-1 text-xs text-ink-faint">{place}</span>
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
                vs {data.enemy_laner?.name}
              </Link>
            )}
          </div>
          {s.reasons.length > 0 && (
            <ul className="mt-0.5 text-xs leading-relaxed text-ink-dim">
              {s.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
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
                    {recordLine(e, e.kind === 'enemy' ? 'against' : 'beside')}
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
            games={s.games}
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
              games={c.games}
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
