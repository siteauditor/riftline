import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useQuery } from '@tanstack/react-query'

import ArtHeader from '../components/ArtHeader'
import Head from '../components/Head'
import SelectField from '../components/SelectField'
import ChampionPicker from '../components/ChampionPicker'
import PositionIcon from '../components/PositionIcon'
import { EmptyState, ErrorView } from '../components/StateViews'
import {
  api,
  PLATFORMS,
  POSITIONS,
  type ChampionStatic,
  type DraftEvidence,
  type DraftResponse,
  type DraftSuggestion,
} from '../lib/api'
import { compact, parseRiotId, pct, positionLabel } from '../lib/format'
import { queries } from '../lib/queries'
import { heads } from '../lib/seo'
import { lastRegion, lastRiotId, rememberRegion, rememberRiotId } from '../lib/storage'
import { useChampionArt } from '../lib/useChampionArt'
import { useDebounced } from '../lib/useDebounced'
import { Chip, ChipGroup } from '@/components/ui/chips'
import { toast } from 'sonner'

const COMFORT_LEVELS = [
  { value: 0, label: 'Off' },
  { value: 0.15, label: 'Light' },
  { value: 0.4, label: 'Strong' },
]

// Long enough that typing a Riot ID is one request, short enough that adding a
// champion re-ranks while the hand is still on the mouse.
const RERANK_MS = 250

/**
 * Draft assistant.
 *
 * Every suggestion shows its reasoning, and the list is ordered by what the
 * records actually support rather than what they claim: measured on the live
 * API on 2026-09-21, a 10-2 lane record over twelve games was lifting a pick
 * from 50.7% to 60.0% and putting it top. The page therefore shows both the
 * supported score it ranks on and the unrestrained "if that holds" figure.
 *
 * The board lives in the URL so a draft can be shared or reloaded. The Riot ID
 * does not: it identifies a person, so it stays in this browser.
 */
export default function Draft() {
  const [search, setSearch] = useSearchParams()
  const [platform, setPlatform] = useState(() => lastRegion() ?? 'euw1')
  const [riotId, setRiotId] = useState(() => lastRiotId() ?? '')

  const ids = (key: string): number[] =>
    (search.get(key) ?? '')
      .split(',')
      .map(Number)
      .filter((n) => Number.isFinite(n) && n > 0)

  const position = (search.get('role') ?? 'MIDDLE').toUpperCase()
  const allies = ids('allies')
  const enemies = ids('enemies')
  const bans = ids('bans')
  const laneId = Number(search.get('lane')) || null
  const lane = laneId && enemies.includes(laneId) ? laneId : null
  const minGames = Math.max(1, Number(search.get('min')) || 20)
  const comfort = COMFORT_LEVELS.some((c) => c.value === Number(search.get('comfort')))
    ? Number(search.get('comfort'))
    : 0.15

  function set(patch: Record<string, string | null>) {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === '') next.delete(key)
      else next.set(key, value)
    }
    setSearch(next, { replace: true })
  }

  const setIds = (key: string, list: number[]) =>
    set({ [key]: list.length ? list.join(',') : null })

  const { data: championData } = useQuery({
    ...queries.champions(),
    staleTime: 6 * 60 * 60 * 1000,
  })
  const championById = useMemo(
    () => new Map((championData?.champions ?? []).map((c) => [c.id, c])),
    [championData],
  )

  // Settled, so dragging a slider or typing an ID is not one request per key.
  const settledRiotId = useDebounced(riotId, RERANK_MS)
  const board = useDebounced(
    { position, allies, enemies, lane, bans, minGames, comfort },
    RERANK_MS,
  )
  const parsed = parseRiotId(settledRiotId)

  const draft = useQuery({
    queryKey: ['draft', board, platform, parsed?.name ?? '', parsed?.tag ?? ''],
    queryFn: () =>
      api.draft({
        position: board.position,
        allies: board.allies,
        enemies: board.enemies,
        bans: board.bans,
        enemy_laner: board.lane,
        min_games: board.minGames,
        comfort_weight: board.comfort,
        platform: parsed ? platform : null,
        game_name: parsed?.name ?? null,
        tag_line: parsed?.tag ?? null,
      }),
    // The previous ranking stays on screen while the next one loads, so adding
    // a champion never blanks the page.
    placeholderData: keepPreviousData,
    retry: false,
  })

  const corpus = useQuery(queries.corpus())
  const empty = corpus.data && corpus.data.total_matches === 0
  const boardIsSet = allies.length + enemies.length + bans.length > 0 || lane !== null
  // Who you are facing, or failing that what the list is telling you to pick.
  const heroArt = useChampionArt(lane ?? draft.data?.suggestions[0]?.champion.id)

  return (
    <div>
      <Head {...heads.draft()} />
      <ArtHeader art={heroArt}>
        <p className="eyebrow">{positionLabel(position)} · pick phase</p>
        <h1 className="display mt-1 text-[clamp(2rem,5vw,3.2rem)] font-800 uppercase leading-none tracking-[-0.01em] text-ink">
          Draft assistant
        </h1>
        <p className="mt-3 max-w-prose text-sm leading-relaxed text-ink-dim">
          Pick your role, then fill in the draft as it happens. Suggestions are ranked by
          what the records can support, not by what a handful of games claims, and every
          row shows where its number came from.
        </p>
      </ArtHeader>

      <div className="mx-auto max-w-[1280px] px-4 py-6">

      {empty ? (
        <div className="mt-6">
          <EmptyState
            title="No matches ingested yet"
            body="Draft advice is built from a corpus of matches. Run the crawler first: python -m scripts.ingest crawl --target 500, then python -m scripts.ingest aggregate."
          />
        </div>
      ) : (
        <div className="mt-5 grid gap-6 lg:grid-cols-[320px_1fr]">
          {/* The board */}
          <aside className="space-y-4">
            <div>
              <span className="mb-1 block text-xs text-ink-faint">Your role</span>
              <ChipGroup label="Your role" className="gap-1">
                {POSITIONS.map((p) => (
                  <Chip key={p.id} size="sm" active={position === p.id} onClick={() => set({ role: p.id })}>
                    <PositionIcon position={p.id} className="size-4" />
                    {p.label}
                  </Chip>
                ))}
              </ChipGroup>
            </div>

            <Slot
              label="Your team"
              placeholder="Add an ally"
              ids={allies}
              championById={championById}
              onAdd={(id) => setIds('allies', [...allies, id])}
              onRemove={(id) => setIds('allies', allies.filter((c) => c !== id))}
            />

            <Slot
              label="Enemy team"
              placeholder="Add an enemy"
              ids={enemies}
              championById={championById}
              onAdd={(id) => setIds('enemies', [...enemies, id])}
              onRemove={(id) => {
                setIds('enemies', enemies.filter((c) => c !== id))
                if (lane === id) set({ lane: null })
              }}
              markLabel="lane"
              marked={lane}
              onMark={(id) => set({ lane: lane === id ? null : String(id) })}
            />

            <Slot
              label="Banned"
              placeholder="Add a champion"
              ids={bans}
              championById={championById}
              onAdd={(id) => setIds('bans', [...bans, id])}
              onRemove={(id) => setIds('bans', bans.filter((c) => c !== id))}
            />

            <div>
              <span className="mb-1 block text-xs text-ink-faint">
                Your Riot ID (optional, weighs your mastery)
              </span>
              <div className="flex gap-1">
                <SelectField
                  ariaLabel="Region"
                  value={platform}
                  onValueChange={(v) => {
                    setPlatform(v)
                    rememberRegion(v)
                  }}
                  triggerClassName="h-10 shrink-0"
                  options={PLATFORMS.map((p) => ({ value: p.id, label: p.label }))}
                />
                <input
                  value={riotId}
                  onChange={(e) => {
                    setRiotId(e.target.value)
                    rememberRiotId(e.target.value)
                  }}
                  placeholder="Caps#EUW"
                  className="control h-10 min-w-0 flex-1 px-3 text-sm placeholder:text-ink-faint"
                />
              </div>
              <p className="mt-1 text-[11px] text-ink-faint">
                Remembered on this device, and kept out of the link.
              </p>
            </div>

            <SelectField
              label="Weigh what you can play"
              className="justify-between text-sm"
              value={String(comfort)}
              onValueChange={(v) => set({ comfort: v })}
              disabled={!parsed}
              options={COMFORT_LEVELS.map((c) => ({ value: String(c.value), label: c.label }))}
            />

            <label className="flex items-center justify-between gap-2 text-sm text-ink-dim">
              <span className="text-xs text-ink-faint">Min games per champion</span>
              <input
                type="number"
                min={1}
                value={minGames}
                onChange={(e) => set({ min: String(Math.max(1, Number(e.target.value) || 1)) })}
                className="control tnum w-16"
              />
            </label>

            {boardIsSet && (
              <button
                onClick={() => {
                  set({ allies: null, enemies: null, bans: null, lane: null })
                  toast('Board cleared')
                }}
                className="text-xs text-ink-faint underline decoration-line underline-offset-2 transition-colors hover:text-ink"
              >
                Clear the board
              </button>
            )}
          </aside>

          {/* Results */}
          <div className="min-w-0">
            {draft.isError && (
              <ErrorView error={draft.error} onRetry={() => draft.refetch()} />
            )}

            {draft.isLoading && <SuggestionSkeleton />}

            {draft.data && <Results data={draft.data} stale={draft.isPlaceholderData} />}
          </div>
        </div>
      )}
    </div>
    </div>
  )
}

/** One side of the board: a picker and the champions already in it. */
function Slot({
  label,
  placeholder,
  ids,
  championById,
  onAdd,
  onRemove,
  markLabel,
  marked,
  onMark,
}: {
  label: string
  placeholder: string
  ids: number[]
  championById: Map<number, ChampionStatic>
  onAdd: (id: number) => void
  onRemove: (id: number) => void
  markLabel?: string
  marked?: number | null
  onMark?: (id: number) => void
}) {
  return (
    <div>
      <ChampionPicker
        label={label}
        value={null}
        onChange={(id) => id && !ids.includes(id) && onAdd(id)}
        placeholder={placeholder}
      />
      {ids.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {ids.map((id) => {
            const champion = championById.get(id)
            const isMarked = marked === id
            return (
              <li
                key={id}
                className={`flex items-center rounded-sm border bg-raised text-xs ${
                  isMarked ? 'border-gold text-gold-bright' : 'border-line text-ink-dim'
                }`}
              >
                <button
                  onClick={() => onRemove(id)}
                  className="flex items-center gap-1.5 py-1 pl-1 pr-1.5 transition-colors hover:text-loss"
                  title={`Remove ${champion?.name ?? id}`}
                >
                  {champion?.icon_url && (
                    <img src={champion.icon_url} alt="" className="size-4 rounded-sm" />
                  )}
                  {champion?.name ?? `Champion ${id}`}
                  <span aria-hidden>✕</span>
                </button>
                {onMark && (
                  <button
                    onClick={() => onMark(id)}
                    aria-pressed={isMarked}
                    title={
                      isMarked
                        ? 'Counted as your lane opponent'
                        : `Mark ${champion?.name ?? id} as your lane opponent`
                    }
                    className={`border-l px-1.5 py-1 transition-colors ${
                      isMarked
                        ? 'border-gold/40 text-gold-bright'
                        : 'border-line text-ink-faint hover:text-ink'
                    }`}
                  >
                    {isMarked ? `in my ${markLabel}` : markLabel}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function SuggestionSkeleton() {
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

function Results({ data, stale }: { data: DraftResponse; stale: boolean }) {
  return (
    <div className={stale ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
      <div className="flex flex-wrap items-baseline gap-x-3 text-xs text-ink-faint">
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
        <span>{data.personalised ? 'weighted by your mastery' : 'not personalised'}</span>
      </div>

      <ol className="mt-3">
        {data.suggestions.map((s, i) => (
          <SuggestionRow key={s.champion.id} suggestion={s} place={i + 1} />
        ))}
      </ol>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Bans data={data} />
        <HowScored data={data} />
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

function HowScored({ data }: { data: DraftResponse }) {
  const m = data.model
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
        Mastery is a preference, not evidence: at the strongest setting a fully mastered
        champion gains{' '}
        <span className="tnum text-ink">
          {(m.comfort_max_bonus * 100).toFixed(1)} points
        </span>
        , scaled by the weight you choose (now{' '}
        <span className="tnum text-ink">{m.comfort_weight}</span>).
      </p>
    </details>
  )
}
