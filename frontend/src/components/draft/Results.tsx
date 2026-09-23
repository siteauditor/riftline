import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'

import { EmptyState } from '../StateViews'
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
  return (
    <div aria-busy={stale} className={stale ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
      <div role="status" className="flex flex-wrap items-baseline gap-x-3 text-xs text-ink-faint">
        <span>Patch {data.patch}</span>
        <span>{positionLabel(data.position)}</span>
        {data.enemy_laner && <span>against {data.enemy_laner.name}</span>}
        {data.enemies.length > 0 && (
          <span>
            {data.enemies.length} enemy {data.enemies.length === 1 ? 'pick' : 'picks'} read
          </span>
        )}
        {data.allies.length > 0 && (
          <span>
            {data.allies.length} {data.allies.length === 1 ? 'ally' : 'allies'} read
          </span>
        )}
        <span>{masteryNote(data, comfort)}</span>
      </div>

      <ol className="mt-3">
        {data.suggestions.map((s, i) => (
          <SuggestionRow key={s.champion.id} suggestion={s} place={i + 1} />
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

function SuggestionRow({ suggestion: s, place }: { suggestion: DraftSuggestion; place: number }) {
  const part = (kind: DraftEvidence['kind']) =>
    s.evidence.filter((e) => e.kind === kind).reduce((sum, e) => sum + e.credible_lift, 0)
  const parts = [
    { label: 'Baseline', value: s.base_win_rate, absolute: true, title: `over ${s.games} games` },
    { label: 'Lane', value: part('lane'), title: sampleTitle(s, 'lane') },
    { label: 'Enemy team', value: part('enemy'), title: sampleTitle(s, 'enemy') },
    { label: 'Allies', value: part('ally'), title: sampleTitle(s, 'ally') },
    { label: 'Comfort', value: s.comfort_bonus, title: `${compact(s.mastery_points)} mastery points` },
  ].filter((p) => p.absolute || Math.abs(p.value) >= 0.0005)
  // The cap can bite when several records pull the same way, and then the parts
  // do not add up to the total. Saying so beats letting the reader check.
  const uncapped = part('lane') + part('enemy') + part('ally')
  const capped = Math.abs(uncapped - s.context_lift) > 0.0005
  // With nothing locked in there is no breakdown yet: the reason line and the
  // parts line both read "baseline over N games", which the games count on the
  // right has already said. Three copies of one fact is what made an opening
  // list of fifteen rows look like a form rather than a ranking.
  const bare = parts.length === 1 && s.reasons.length === 1

  return (
    <li className="border-b border-line-soft px-1 py-2.5 lift">
      <div className="flex gap-3">
        <span className="tnum w-5 shrink-0 pt-1 text-xs text-ink-faint">{place}</span>
        {s.champion.icon_url && (
          <img
            src={s.champion.icon_url}
            alt=""
            className="size-10 shrink-0 rounded-sm"
            loading="lazy"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <p className="font-display text-sm font-700 text-ink">{s.champion.name}</p>
            <p
              className="tnum text-sm font-600 text-gold-bright"
              title="Baseline plus what the records support, plus comfort. What this list is ranked by."
            >
              {pct(s.score, 1)}
            </p>
            {Math.abs(s.adjusted_win_rate - s.score) > 0.001 && (
              <p
                className="tnum text-xs text-ink-faint"
                title="Baseline plus everything those records claim, before their own uncertainty is taken off."
              >
                {pct(s.adjusted_win_rate, 1)} if the records hold
              </p>
            )}
          </div>
          {!bare && (
            <ul className="mt-0.5 text-xs leading-relaxed text-ink-dim">
              {s.reasons.map((r, j) => (
                <li key={j}>{r}</li>
              ))}
            </ul>
          )}
          <p className={`${bare ? 'hidden' : 'mt-1 flex'} flex-wrap gap-x-2.5 gap-y-1 text-[11px]`}>
            {parts.map((p) => (
              <span key={p.label} title={p.title} className="text-ink-faint">
                {p.label}{' '}
                <span
                  className="tnum"
                  style={{
                    color: p.absolute
                      ? 'var(--color-ink)'
                      : p.value > 0
                        ? 'var(--color-win)'
                        : 'var(--color-loss)',
                  }}
                >
                  {p.absolute
                    ? pct(p.value, 1)
                    : `${p.value > 0 ? '+' : ''}${(p.value * 100).toFixed(1)}`}
                </span>
              </span>
            ))}
            {capped && <span className="text-ink-faint">capped</span>}
          </p>
        </div>
        <div className="shrink-0 text-right text-xs text-ink-faint">
          <ScoreBar score={s.score} />
          <p className="tnum">{compact(s.games)} games</p>
          {s.mastery_points > 0 && <p className="tnum">{compact(s.mastery_points)} pts</p>}
        </div>
      </div>
    </li>
  )
}

/**
 * Where this pick sits against an even game.
 *
 * The scale is fixed at 40 to 60 so two rows can be compared by eye, and the
 * tick is 50. Most rows sit left of it, which is not a bug: the list is ranked
 * on the low end of what each record supports, and a lower bound is below the
 * rate it came from. The bar is the one place that is visible at a glance
 * rather than in a tooltip.
 */
const BAR_LOW = 0.4
const BAR_HIGH = 0.6

function ScoreBar({ score }: { score: number }) {
  const place = (v: number) =>
    ((Math.min(Math.max(v, BAR_LOW), BAR_HIGH) - BAR_LOW) / (BAR_HIGH - BAR_LOW)) * 100
  const even = place(0.5)
  const here = place(score)
  const winning = score >= 0.5
  return (
    <span
      className="relative mb-1.5 hidden h-1.5 w-36 bg-raised sm:block"
      title={`${pct(score, 1)} is what this pick's records support. The bar runs 40 to 60%.`}
      aria-hidden
    >
      <span
        className="absolute inset-y-0"
        style={{
          left: `${Math.min(even, here)}%`,
          width: `${Math.max(Math.abs(here - even), 1)}%`,
          background: winning
            ? 'var(--color-gold-bright)'
            : 'color-mix(in srgb, var(--color-ink-dim) 70%, transparent)',
        }}
      />
      <span className="absolute -inset-y-[3px] w-px bg-ink-faint" style={{ left: `${even}%` }} />
    </span>
  )
}

function sampleTitle(s: DraftSuggestion, kind: DraftEvidence['kind']): string {
  const rows = s.evidence.filter((e) => e.kind === kind)
  if (rows.length === 0) return 'no records'
  return rows
    .map(
      (e) =>
        `${e.champion.name}: ${(e.win_rate * 100).toFixed(0)}% over ${e.games} games, ` +
        `claims ${(e.lift * 100).toFixed(1)}, supports ${(e.credible_lift * 100).toFixed(1)}`,
    )
    .join(' | ')
}

function Bans({ data }: { data: DraftResponse }) {
  if (data.ban_candidates.length === 0) return null
  return (
    <section>
      <h2 className="eyebrow">Worth banning</h2>
      <p className="mt-0.5 text-[11px] leading-relaxed text-ink-faint">
        {data.bans_read_the_draft
          ? 'Strongest against the champions your team has locked in.'
          : data.enemies.length > 0
            ? 'None of your team is locked in yet, so these are simply the patch’s strongest picks.'
            : 'Nothing is locked in yet, so these are simply the patch’s strongest picks.'}
      </p>
      <ol className="mt-2">
        {data.ban_candidates.map((c) => (
          <li
            key={c.champion.id}
            className="flex items-center gap-2.5 border-b border-line-soft py-2"
          >
            {c.champion.icon_url && (
              <img src={c.champion.icon_url} alt="" className="size-8 rounded-sm" loading="lazy" />
            )}
            <div className="min-w-0 flex-1">
              <p className="font-display text-sm font-600 text-ink">
                {c.champion.name}
                <span className="ml-1.5 text-[11px] text-ink-faint">
                  {positionLabel(c.position)}
                </span>
              </p>
              <p className="text-[11px] leading-snug text-ink-faint">{c.reasons.join('. ')}</p>
            </div>
            <span className="tnum shrink-0 text-sm font-600 text-loss">{pct(c.score, 1)}</span>
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
  return (
    <details className="frame px-4 py-3 text-xs leading-relaxed text-ink-dim">
      <summary className="cursor-pointer text-ink">How this is scored</summary>
      <p className="mt-2">
        Every champion starts at the win rate its own sample can defend in this role on
        patch {data.patch}. Each record on the board, your lane, each enemy pick and each
        ally, moves that number toward what it shows, by{' '}
        <span className="tnum text-ink">games / (games + k)</span> of the distance: k is{' '}
        <span className="tnum text-ink">{m.lane_shrinkage}</span> in lane,{' '}
        <span className="tnum text-ink">{m.team_shrinkage}</span> for the enemy team and{' '}
        <span className="tnum text-ink">{m.ally_shrinkage}</span> for allies.
      </p>
      <p className="mt-2">
        Each record then gives up its own margin of error, so a 10-2 over twelve games
        argues for a few points rather than nine, and a 55% over twenty argues for
        nothing. The board as a whole cannot move a pick more than{' '}
        <span className="tnum text-ink">{(m.context_lift_cap * 100).toFixed(0)} points</span>.
      </p>
      <p className="mt-2">
        Mastery is a preference, not evidence: a fully mastered champion gains up to{' '}
        <span className="tnum text-ink">{points(strongest.value)} points</span> at{' '}
        {strongest.label}. The weight is now {level.label}
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
